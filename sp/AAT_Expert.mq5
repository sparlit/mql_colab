#property copyright "Copyright 2026, Autonomous AutoTrader"
#property link      "https://github.com/yourusername/AAT"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Expert\Expert.mqh>
#include "../include/AAT_SocketClient.mqh"
#include "../include/AAT_Protocol.mqh"
#include "../include/AAT_TradingEngine.mqh"

//+------------------------------------------------------------------+
//|                                                      AAT_Expert.mq5 |
//|                        Copyright 2026, MetaQuotes Software Corp. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

//--- input parameters
input string      ServerIP        = "127.0.0.1";    // Python server IP address
input int         ServerPort      = 5555;           // Python server port
input bool        EncryptionEnabled = true;         // Enable AES-256 encryption
input bool        AuthRequired      = true;         // Require authentication
input double      RiskPerTrade      = 0.02;         // Risk per trade (2%)
input double      MaxDrawdownHalt   = 0.05;         // Max drawdown to halt trading (5%)
input double      DailyLossLimit    = 0.02;         // Daily loss limit (2%)
input int         ConsecutiveLossPause = 3;         // Losses before pause
input int         PauseDurationMinutes = 30;        // Pause duration in minutes
input double      SpreadFilterMultiplier = 2.0;     // Skip if spread > 2x average
input double      SlippageGuardThreshold = 0.10;    // Abort if slippage > 10% of profit
input double      ConsensusThreshold   = 0.7;       // |score| >= 0.7 for execution

//--- global variables
CAATSocketClient  m_socket_client;
CTrade            m_trade;
CAATTradingEngine m_trading_engine;
datetime          m_last_tick_time;
bool              m_is_initialized = false;
double            m_account_balance = 0.0;
double            m_equity = 0.0;
double            m_free_margin = 0.0;
double            m_daily_start_balance = 0.0;
int               m_consecutive_losses = 0;
datetime          m_last_loss_time = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   // Initialize trading engine
   if(!m_trading_engine.Init(ServerIP, ServerPort, EncryptionEnabled, AuthRequired))
   {
      Print("Failed to initialize trading engine. Running in offline mode.");
   }
   else
   {
      Print("Trading engine initialized successfully");
      // Start trading (could be made configurable)
      m_trading_engine.SetTradingState(TRADING_STATE_ON);
   }

   m_is_initialized = true;
   m_last_tick_time = TimeCurrent();

   Print("AAT Expert initialized successfully");
   PrintFormat("Account balance: %.2f", m_account_balance);
   PrintFormat("Risk per trade: %.2f%%", RiskPerTrade * 100);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   m_socket_client.Disconnect();
   Print("AAT Expert deinitialized");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Delegate to trading engine
   m_trading_engine.OnTick();
}

//+------------------------------------------------------------------+
//| Process incoming messages from Python                            |
//+------------------------------------------------------------------+
void ProcessIncomingMessages()
{
   string message_type, symbol, payload;
   datetime timestamp;

   // Process all available messages
   while(m_socket_client.IsConnected() &&
         m_socket_client.ProcessIncomingMessage(message_type, symbol, timestamp, payload))
   {
      // Handle different message types
      if(message_type == "PONG")
      {
         // Handle PONG response
         // Extract uptime from payload if needed
      }
      else if(message_type == "CONSENSUS_RSP")
      {
         // Handle trading signal from Python
         HandleConsensusResponse(payload);
      }
      else if(message_type == "RISK_RSP")
      {
         // Handle risk response from Python
         HandleRiskResponse(payload);
      }
      // Add other message types as needed
   }
}

//+------------------------------------------------------------------+
//| Handle consensus response from Python                            |
//+------------------------------------------------------------------+
void HandleConsensusResponse(const string &payload_json)
{
   // Parse JSON payload to get direction, confidence, etc.
   // For simplicity, we'll do basic string parsing
   // In a real implementation, use a proper JSON parser

   string direction = "";
   double confidence = 0.0;

   // Extract direction
   int dir_pos = StringFind(payload_json, "\"direction\":\"");
   if(dir_pos != -1)
   {
      dir_pos += 12; // Length of "\"direction\":\""
      int dir_end = StringFind(payload_json, '"', dir_pos);
      if(dir_end != -1)
         direction = StringSubstr(payload_json, dir_pos, dir_end - dir_pos);
   }

   // Extract confidence
   int conf_pos = StringFind(payload_json, "\"confidence\":");
   if(conf_pos != -1)
   {
      conf_pos += 13; // Length of "\"confidence\":"
      int conf_end = StringFind(payload_json, ',', conf_pos);
      if(conf_end == -1)
         conf_end = StringFind(payload_json, '}', conf_pos);
      if(conf_end != -1)
      {
         string conf_str = StringSubstr(payload_json, conf_pos, conf_end - conf_pos);
         confidence = (double)StringToDouble(conf_str);
      }
   }

   // Check if signal meets threshold
   if(StringLen(direction) > 0 && confidence >= ConsensusThreshold)
   {
      // Get symbol from chart
      string symbol = Symbol();

      // Calculate lot size based on risk management
      double lot_size = CalculateLotSize(symbol, direction);

      if(lot_size > 0)
      {
         // Check if we should trade based on risk management
         if(CheckRiskManagement(symbol, direction, lot_size))
         {
            // Execute trade
            ExecuteTrade(symbol, direction, lot_size);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Handle risk response from Python                                 |
//+------------------------------------------------------------------+
void HandleRiskResponse(const string &payload_json)
{
   bool approved = false;
   string reason = "";
   double adjusted_lots = 0.0;

   // Extract approved
   int app_pos = StringFind(payload_json, "\"approved\":");
   if(app_pos != -1)
   {
      app_pos += 11; // Length of "\"approved\":"
      string app_str = StringSubstr(payload_json, app_pos, 4); // "true" or "false"
      approved = (app_str == "true");
   }

   // Extract reason
   int reason_pos = StringFind(payload_json, "\"reason\":\"");
   if(reason_pos != -1)
   {
      reason_pos += 10; // Length of "\"reason\":\""
      int reason_end = StringFind(payload_json, '"', reason_pos);
      if(reason_end != -1)
         reason = StringSubstr(payload_json, reason_pos, reason_end - reason_pos);
   }

   // Extract adjusted_lots
   int lots_pos = StringFind(payload_json, "\"adjusted_lots\":");
   if(lots_pos != -1)
   {
      lots_pos += 16; // Length of "\"adjusted_lots\":"
      int lots_end = StringFind(payload_json, ',', lots_pos);
      if(lots_end == -1)
         lots_end = StringFind(payload_json, '}', lots_pos);
      if(lots_end != -1)
      {
         string lots_str = StringSubstr(payload_json, lots_pos, lots_end - lots_pos);
         adjusted_lots = (double)StringToDouble(lots_str);
      }
   }

   // Handle the risk response (for now, just print)
   if(approved)
   {
      PrintFormat("Risk check approved: %s. Adjusted lots: %.2f", reason, adjusted_lots);
   }
   else
   {
      PrintFormat("Risk check rejected: %s", reason);
   }
}

//+------------------------------------------------------------------+
//| Calculate lot size based on risk management                      |
//+------------------------------------------------------------------+
double CalculateLotSize(string symbol, string direction)
{
   // Get symbol info
   if(!SymbolSelect(symbol, true))
   {
      PrintFormat("Failed to select symbol %s", symbol);
      return 0.0;
   }

   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TICK_VALUE);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TICK_SIZE);

   // For simplicity, we'll use a fixed stop loss of 50 points
   // In a real implementation, this would come from strategy or technical analysis
   double stop_loss_points = 50.0;

   // Calculate money at risk
   double money_at_risk = m_account_balance * RiskPerTrade;

   // Calculate lot size
   double lot_size = money_at_risk / (stop_loss_points * point * tick_value / tick_size);

   // Normalize lot size
   double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);

   lot_size = MathFloor(lot_size / lot_step) * lot_step;

   if(lot_size < min_lot)
      lot_size = 0.0;
   else if(lot_size > max_lot)
      lot_size = max_lot;

   return lot_size;
}

//+------------------------------------------------------------------+
//| Check risk management constraints                                |
//+------------------------------------------------------------------+
bool CheckRiskManagement(string symbol, string direction, double lots)
{
   // Check max drawdown halt
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);

   if(balance > 0)
   {
      double drawdown = (balance - equity) / balance;
      if(drawdown > MaxDrawdownHalt)
      {
         PrintFormat("Trade blocked: Drawdown %.2f%% exceeds limit %.2f%%",
                     drawdown*100, MaxDrawdownHalt*100);
         return false;
      }
   }

   // Check daily loss limit
   if(!CheckDailyLossLimit())
   {
      PrintFormat("Trade blocked: Daily loss limit exceeded");
      return false;
   }

   // Check consecutive losses
   if(!CheckConsecutiveLosses())
   {
      PrintFormat("Trade blocked: Consecutive loss limit exceeded");
      return false;
   }

   // Check margin requirements
   double margin_required = m_trade.MarginCalculation(symbol,
                                                     (direction == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                                                     lots);
   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);

   if(margin_required > free_margin)
   {
      PrintFormat("Trade blocked: Insufficient margin. Required: %.2f, Free: %.2f",
                  margin_required, free_margin);
      return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| Execute trade                                                    |
//+------------------------------------------------------------------+
void ExecuteTrade(string symbol, string direction, double lots)
{
   // Check if trading is allowed
   if(!IsTradeAllowed())
   {
      Print("Trade blocked: Trading is not allowed");
      return;
   }

   // Get current prices
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);

   // Determine order type and price
   ENUM_ORDER_TYPE order_type;
   double price;

   if(direction == "BUY")
   {
      order_type = ORDER_TYPE_BUY;
      price = ask;
   }
   else if(direction == "SELL")
   {
      order_type = ORDER_TYPE_SELL;
      price = bid;
   }
   else
   {
      PrintFormat("Invalid direction: %s", direction);
      return;
   }

   // Calculate stop loss and take profit (simplified)
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double stop_loss = 0.0;
   double take_profit = 0.0;

   if(order_type == ORDER_TYPE_BUY)
   {
      stop_loss = price - 50 * point;  // 50 points SL
      take_profit = price + 100 * point; // 100 points TP (2:1 reward:risk)
   }
   else
   {
      stop_loss = price + 50 * point;  // 50 points SL
      take_profit = price - 100 * point; // 100 points TP (2:1 reward:risk)
   }

   // Place the trade
   if(m_trade.OrderSend(symbol, order_type, lots, price, 3,  // 3 points slippage
                        stop_loss, take_profit, "AAT Trade",
                        123456, 0, clrGreen))
   {
      PrintFormat("Trade executed: %s %s %.2f lots at %.5f",
                  direction, symbol, lots, price);
      PrintFormat("SL: %.5f, TP: %.5f", stop_loss, take_profit);
   }
   else
   {
      PrintFormat("Trade failed: %s", m_trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Send OHLC data to Python                                         |
//+------------------------------------------------------------------+
void SendOHLCData()
{
   // Get OHLC data for multiple timeframes
   string timeframes[] = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"};
   string symbol = Symbol();

   for(int i=0; i<ArraySize(timeframes); i++)
   {
      string tf = timeframes[i];

      // Get bar data
      int bars_count = 100; // Last 100 bars
      double open[], high[], low[], close[];
      long volume[];
      datetime time[];

      int copied = CopyRates(symbol, PeriodStringToEnum(tf), 0, bars_count, time, open, high, low, close, volume);

      if(copied > 0)
      {
         // Send to Python
         m_socket_client.SendOHLCPush(symbol, tf, open, high, low, close, volume, 0, copied);
      }
   }
}

//+------------------------------------------------------------------+
//| Helper: Convert period string to ENUM_TIMEFRAMES                 |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES PeriodStringToEnum(string timeframe)
{
   if(timeframe == "M1")   return PERIOD_M1;
   if(timeframe == "M5")   return PERIOD_M5;
   if(timeframe == "M15")  return PERIOD_M15;
   if(timeframe == "M30")  return PERIOD_M30;
   if(timeframe == "H1")   return PERIOD_H1;
   if(timeframe == "H4")   return PERIOD_H4;
   if(timeframe == "D1")   return PERIOD_D1;
   if(timeframe == "W1")   return PERIOD_W1;
   return PERIOD_CURRENT;  // Default
}

//+------------------------------------------------------------------+
//| Check daily loss limit                                           |
//+------------------------------------------------------------------+
bool CheckDailyLossLimit()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);

   // Reset daily balance at start of day
   datetime today = TimeCurrent();
   if(TimeDay(today) != TimeDay(m_last_tick_time) || m_daily_start_balance == 0.0)
   {
      m_daily_start_balance = balance;
      m_last_tick_time = today;
   }

   // Check if daily loss limit exceeded
   double daily_loss = (m_daily_start_balance - balance) / m_daily_start_balance;
   if(daily_loss > DailyLossLimit)
      return false;

   return true;
}

//+------------------------------------------------------------------+
//| Check consecutive losses                                         |
//+------------------------------------------------------------------+
bool CheckConsecutiveLosses()
{
   // Reset consecutive loss counter if pause duration has passed
   if(m_last_loss_time > 0 &&
      TimeCurrent() - m_last_loss_time > PauseDurationMinutes * 60)
   {
      m_consecutive_losses = 0;
   }

   return m_consecutive_losses < ConsecutiveLossPause;
}

//+------------------------------------------------------------------+
//| Check if trading is allowed (based on time, etc.)                |
//+------------------------------------------------------------------+
bool IsTradeAllowed()
{
   // Check if we're in a tradeable time period
   // For now, always allow trading
   // In a real implementation, you might want to avoid trading during news, etc.
   return true;
}