//+------------------------------------------------------------------+
//|                                         UltraKanbanDashboard.mq5 |
//|                                  Copyright 2026, Quant Systems   |
//|                                             https://mql5.com |
//+------------------------------------------------------------------+
#property copyright   "Copyright 2026"
#property link        "https://mql5.com"
#property version     "2.52"
#property description "Ultra High-Density Live Kanban Trading Interface"
#property indicator_chart_window

//--- Include base structural classes for optimal object rendering
#include <ChartObjects\ChartObjectsLines.mqh>
#include <ChartObjects\ChartObjectsTxtControls.mqh>

//--- UI Theme Configuration Profile
input group "--- UI THEME STYLING ---"
input color InpCanvasBg     = C'14,17,20';     // Deep Matrix Dark Background
input color InpHeaderBg     = C'22,27,33';     // Column Header Container Fill
input color InpCardBg       = C'19,23,28';     // High-Contrast Data Card Fill
input color InpTextMuted    = C'139,148,158';  // Desaturated Label Grey
input color InpTextMain     = C'240,246,252';  // High-Readability White
input color InpBullishColor = C'57,255,20';    // Vibrant Neon Green
input color InpBearishColor = C'255,49,49';    // Sharp Signal Crimson
input color InpAlertColor   = C'255,193,7';     // Warning Accent Gold

//--- Global Engine Variables (Strict explicit dimension bounds)
string SymbolsList[4]  = {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD"};
ENUM_TIMEFRAMES TF[4]  = {PERIOD_M15, PERIOD_H1, PERIOD_H4, PERIOD_D1};
int TotalColumns       = 5;
int ColumnWidth        = 265;
int ColumnGap          = 12;
int StartX             = 15;
int StartY             = 45;

//--- Forward declarations to eliminate structural ordering compiler lookups
void UpdateDashboardCoreEngine(void);
void RenderFullCanvas(void);
void RenderKanbanSwimlane(string columnHeader, string prefix, int x, int y);
double CalculateEMA(string symbol, ENUM_TIMEFRAMES timeframe, int period, int shift);
double CalculateClosePrice(string symbol, ENUM_TIMEFRAMES timeframe, int shift);
void RenderLiveField(string tag, string keyLabel, string valLabel, int x, int y, color keyColor, color valColor);
void RenderLiveHeaderLabel(string tag, string c1, string c2, string c3, string c4, int x, int y);
void RenderGridRow(string tag, string asset, string bid, string ask, string spread, int x, int y, color spreadCol);
void RenderMatrixRow(string tag, string asset, string tf1, string tf2, string tf3, int x, int y, color c1, color c2, color c3);

//+------------------------------------------------------------------+
//| Expert Initialization Entry Point                                |
//+------------------------------------------------------------------+
int OnInit()
  {
// Force Chart Window State Optimization (Using verified MQL5 Enums)
   ChartSetInteger(0, CHART_SHOW, false);
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_AUTOSCROLL, false);

   ObjectsDeleteAll(0, "UKB_");

// Build Base Core Visual Kanban Board Grid System
   RenderFullCanvas();

   string ColumnTitles[5] =
     {
      "1. RISK & BALANCE",
      "2. LIVE MARKET WATCH",
      "3. TECHNICAL MATRIX",
      "4. ACTIVE EXPOSURE",
      "5. ENVIRONMENT & CALENDAR"
     };

   for(int i = 0; i < TotalColumns; i++)
     {
      int currentX = StartX + i * (ColumnWidth + ColumnGap);
      RenderKanbanSwimlane(ColumnTitles[i], "UKB_COL_" + IntegerToString(i), currentX, StartY);
     }

// Immediate Initial Data Synchronization Draw Pass
   UpdateDashboardCoreEngine();
   ChartRedraw(0);

   EventSetTimer(1);

// Auxiliary 1-Second Grid Clock Polling Engine Interceptor
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert Deinitialization Clean Routine                            |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, "UKB_");
   ChartSetInteger(0, CHART_SHOW, true);

// Restore core native bars interface
   ChartSetInteger(0, CHART_SHOW_GRID, true);
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| Live Tick Market Interceptor                                     |
//+------------------------------------------------------------------+
void OnTick()
  {
   UpdateDashboardCoreEngine();
  }

//+------------------------------------------------------------------+
//| Timer Clock Polling Routine (Executes Every 1 Second)            |
//+------------------------------------------------------------------+
void OnTimer()
  {
   UpdateDashboardCoreEngine();
  }

//+------------------------------------------------------------------+
//| Render Full Dashboard Background Screen Canvas Overlay           |
//+------------------------------------------------------------------+
void RenderFullCanvas(void)
  {
   CChartObjectRectLabel canvas;
   canvas.Create(0, "UKB_CANVAS_BG", 0, 0, 0, 3000, 2000);
   ObjectSetInteger(0, "UKB_CANVAS_BG", OBJPROP_BGCOLOR, InpCanvasBg);
   canvas.BorderType(BORDER_FLAT);
   canvas.Background(true);
   canvas.Detach();
  }

//+------------------------------------------------------------------+
//| Render Individual Kanban Columns With High Density Layout Frames |
//+------------------------------------------------------------------+
void RenderKanbanSwimlane(string columnHeader, string prefix, int x, int y)
  {
// Swimlane Outer Bound Shadow Panel Frame
   CChartObjectRectLabel lane;
   string bodyName = prefix + "_BODY";
   lane.Create(0, bodyName, 0, x, y, ColumnWidth, 750);
   ObjectSetInteger(0, bodyName, OBJPROP_BGCOLOR, InpCardBg);
   lane.BorderType(BORDER_FLAT);
   lane.Color(C'33,39,47');

// Subtle Border outline
   lane.Detach();

// Header Accent Banner Container Block
   CChartObjectRectLabel head;
   string headName = prefix + "_HEAD";
   head.Create(0, headName, 0, x, y, ColumnWidth, 32);
   ObjectSetInteger(0, headName, OBJPROP_BGCOLOR, InpHeaderBg);
   head.BorderType(BORDER_FLAT);
   head.Detach();

// Text Category Label Overlay
   CChartObjectLabel label;
   label.Create(0, prefix + "_TITLE", 0, x + 12, y + 8);
   label.Description(columnHeader);
   label.Font("Segoe UI");
   label.FontSize(10);
   label.Color(InpTextMain);
   label.Detach();
  }

//+------------------------------------------------------------------+
//| Dynamic Execution Pipeline Engine: Updates live database states |
//+------------------------------------------------------------------+
void UpdateDashboardCoreEngine(void)
  {
//----------------------------------------------------------------
// COLUMN 1: INTEGRATED ACCOUNT CAPITAL PROTECTION RISK DATA PIPELINE
//----------------------------------------------------------------
   double bal    = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq     = AccountInfoDouble(ACCOUNT_EQUITY);
   double pl     = AccountInfoDouble(ACCOUNT_PROFIT);
   double margin = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   double freeM  = AccountInfoDouble(ACCOUNT_FREE_MARGIN);
   long   lev    = AccountInfoInteger(ACCOUNT_LEVERAGE);

   int c1X = StartX + 15;
   int c1Y = StartY + 48;

   RenderLiveField("C1_L1", "Account Balance:", "$" + DoubleToString(bal, 2), c1X, c1Y, InpTextMuted, InpTextMain);
   RenderLiveField("C1_L2", "Net Live Equity:", "$" + DoubleToString(eq, 2), c1X, c1Y + 28, InpTextMuted, InpTextMain);

   color plColor = (pl >= 0) ? InpBullishColor : InpBearishColor;
   RenderLiveField("C1_L3", "Floating Net P/L:", "$" + DoubleToString(pl, 2), c1X, c1Y + 56, InpTextMuted, plColor);

   color marginColor = (margin > 500 || margin == 0) ? InpBullishColor : InpBearishColor;
   string marginStr  = (margin == 0) ? "STABLE" : DoubleToString(margin, 1) + "%";
   RenderLiveField("C1_L4", "Margin Health Lvl:", marginStr, c1X, c1Y + 84, InpTextMuted, marginColor);
   RenderLiveField("C1_L5", "Free Liquid Margin:", "$" + DoubleToString(freeM, 2), c1X, c1Y + 112, InpTextMuted, InpTextMain);
   RenderLiveField("C1_L6", "Leverage Allocation:", "1:" + IntegerToString(lev), c1X, c1Y + 140, InpTextMuted, InpAlertColor);

//----------------------------------------------------------------
// COLUMN 2: MULTI-ASSET TICK STREAMING AND REALTIME SPREAD ENGINE
//----------------------------------------------------------------
   int c2X = StartX + (ColumnWidth + ColumnGap) + 15;
   int c2Y = StartY + 48;

   RenderLiveHeaderLabel("C2_HDR_SYM", "PAIR", "BID", "ASK", "SPREAD", c2X, c2Y);
   c2Y += 22;

   for(int i = 0; i < ArraySize(SymbolsList); i++)
     {
      MqlTick tick;
      if(SymbolInfoTick(SymbolsList[i], tick))
        {
         double spreadValue = (double)(SymbolInfoInteger(SymbolsList[i], SYMBOL_SPREAD)) / 10.0;
         color spreadAlert  = (spreadValue > 3.5) ? InpBearishColor : InpBullishColor;

         RenderGridRow(
            "C2_R_" + SymbolsList[i],
            SymbolsList[i],
            DoubleToString(tick.bid, (int)SymbolInfoInteger(SymbolsList[i], SYMBOL_DIGITS)),
            DoubleToString(tick.ask, (int)SymbolInfoInteger(SymbolsList[i], SYMBOL_DIGITS)),
            DoubleToString(spreadValue, 1) + "p",
            c2X, c2Y + (i * 28),
            spreadAlert
         );
        }
     }

//----------------------------------------------------------------
// COLUMN 3: MULTI-TIMEFRAME DIRECTIONAL TREND ALIGNMENT MATRIX
//----------------------------------------------------------------
   int c3X = StartX + 2 * (ColumnWidth + ColumnGap) + 15;
   int c3Y = StartY + 48;

   RenderLiveHeaderLabel("C3_HDR_MAT", "SYMBOL", "M15", "H1", "H4", c3X, c3Y);
   c3Y += 22;

   for(int s = 0; s < ArraySize(SymbolsList); s++)
     {
      string activeSym = SymbolsList[s];
      string tfStates[3] = {"", "", ""};
      Use code with caution.color  tfColors[3] = {InpTextMain, InpTextMain, InpTextMain};
      for(int t = 0; t < 3; t++)
        {
         double maFast = CalculateEMA(activeSym, TF[t], 20, 0);
         double maSlow = CalculateEMA(activeSym, TF[t], 50, 0);
         double close  = CalculateClosePrice(activeSym, TF[t], 0);
         if(close > maFast && maFast > maSlow)
           {
            tfStates[t] = "BULL";
            tfColors[t] = InpBullishColor;
           }
         else
            if(close < maFast && maFast < maSlow)
              {
               tfStates[t] = "BEAR";
               tfColors[t] = InpBearishColor;
              }
            else
              {
               tfStates[t] = "CHOP";
               tfColors[t] = InpTextMuted;
              }
        }
      RenderMatrixRow("C3_MXR_" + activeSym, activeSym, tfStates[0], tfStates[1], tfStates[2], c3X, c3Y + (s * 28), tfColors[0], tfColors[1], tfColors[2]);
     }
//----------------------------------------------------------------
// COLUMN 4: PRODUCTION EXPOSURE TRACKER & RISK EVALUATOR
//----------------------------------------------------------------
   int c4X = StartX + 3 * (ColumnWidth + ColumnGap) + 15;
   int c4Y = StartY + 48;
   int activeTradesCount = 0;
   double aggregateLots  = 0;
   double totalBuyLots   = 0;
   double totalSellLots  = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetSymbol(i) != "")
        {
         activeTradesCount++;
         double lots = PositionGetDouble(POSITION_VOLUME);
         aggregateLots += lots;
         long type = PositionGetInteger(POSITION_TYPE);
         if(type == POSITION_TYPE_BUY)
            totalBuyLots += lots;
         else
            if(type == POSITION_TYPE_SELL)
               totalSellLots += lots;
        }
     }
   RenderLiveField("C4_L1", "Active Allocations:", IntegerToString(activeTradesCount) + " Open Trades", c4X, c4Y, InpTextMuted, InpTextMain);
   RenderLiveField("C4_L2", "Net Exposure Volume:", DoubleToString(aggregateLots, 2) + " Lots Total", c4X, c4Y + 28, InpTextMuted, InpAlertColor);
   RenderLiveField("C4_L3", "Aggregate Longs:", DoubleToString(totalBuyLots, 2) + " Lots BUY", c4X, c4Y + 56, InpTextMuted, InpBullishColor);
   RenderLiveField("C4_L4", "Aggregate Shorts:", DoubleToString(totalSellLots, 2) + " Lots SELL", c4X, c4Y + 84, InpTextMuted, InpBearishColor);
   RenderLiveField("C4_L5", "Session Net State:", (AccountInfoDouble(ACCOUNT_PROFIT) >= 0)?"PROFITABLE":"DRAWDOWN", c4X, c4Y + 112, InpTextMuted, (AccountInfoDouble(ACCOUNT_PROFIT) >= 0)?InpBullishColor:InpBearishColor);
//----------------------------------------------------------------
// COLUMN 5: REALTIME GLOBAL HIGH-FREQUENCY CLOCK SYNCHRONIZER
//----------------------------------------------------------------
   int c5X = StartX + 4 * (ColumnWidth + ColumnGap) + 15;
   int c5Y = StartY + 48;
   datetime localTime = TimeLocal();
   datetime tradeTime = TimeCurrent();
   RenderLiveField("C5_L1", "Local Operator Time:", TimeToString(localTime, TIME_DATE|TIME_SECONDS), c5X, c5Y, InpTextMuted, InpTextMain);
   RenderLiveField("C5_L2", "Broker Server Clock:", TimeToString(tradeTime, TIME_DATE|TIME_SECONDS), c5X, c5Y + 28, InpTextMuted, InpAlertColor);
   RenderLiveField("C5_L3", "Global GMT Reference:", TimeToString(tradeTime - (datetime)TimeGMTOffset(), TIME_SECONDS), c5X, c5Y + 56, InpTextMuted, InpTextMain);

// Live Operational High-Density Market Session Decoders
   MqlDateTime dt;
   TimeToStruct(tradeTime, dt);
   int currentHour = dt.hour;
   string sessionLondon = (currentHour >= 10 && currentHour <= 18) ? "ONLINE" : "OFFLINE";
   color  colorLondon   = (sessionLondon == "ONLINE") ? InpBullishColor : InpTextMuted;
   RenderLiveField("C5_L4", "London Liquidity:", sessionLondon, c5X, c5Y + 95, InpTextMuted, colorLondon);
   string sessionNY = (currentHour >= 15 && currentHour <= 23) ? "ONLINE" : "OFFLINE";
   color  colorNY   = (sessionNY == "ONLINE") ? InpBullishColor : InpTextMuted;
   RenderLiveField("C5_L5", "New York Liquidity:", sessionNY, c5X, c5Y + 123, InpTextMuted, colorNY);
  }
//+------------------------------------------------------------------+
//| Structural Mathematical Functions Supporting Dashboards          |
//+------------------------------------------------------------------+
double CalculateEMA(string symbol, ENUM_TIMEFRAMES timeframe, int period, int shift) {int handle = iMA(symbol, timeframe, period, 0, MODE_EMA, PRICE_CLOSE);if(handle == INVALID_HANDLE) return(0.0);double buffer[];ArraySetAsSeries(buffer, true);if(CopyBuffer(handle, 0, shift, 1, buffer) < 1) {IndicatorRelease(handle);return(0.0);} IndicatorRelease(handle);return(buffer[0]);}
double CalculateClosePrice(string symbol, ENUM_TIMEFRAMES timeframe, int shift) {double close[];ArraySetAsSeries(close, true);if(CopyClose(symbol, timeframe, shift, 1, close) < 1) return(0.0);return(close[0]);}
//+------------------------------------------------------------------+
//| Low-Level Graphical Field Component Allocators                  |
//+------------------------------------------------------------------+
void RenderLiveField(string tag, string keyLabel, string valLabel, int x, int y, color keyColor, color valColor) {string kTag = "UKB_FIELD_K_" + tag;string vTag = "UKB_FIELD_V_" + tag;if(ObjectFind(0, kTag) < 0) { CChartObjectLabel l; l.Create(0, kTag, 0, x, y); l.Font("Segoe UI"); l.FontSize(9); l.Detach(); } ObjectSetString(0, kTag, OBJPROP_TEXT, keyLabel);ObjectSetInteger(0, kTag, OBJPROP_COLOR, keyColor);if(ObjectFind(0, vTag) < 0) { CChartObjectLabel l; l.Create(0, vTag, 0, x + 125, y); l.Font("Consolas"); l.FontSize(10); l.Detach(); } ObjectSetString(0, vTag, OBJPROP_TEXT, valLabel);ObjectSetInteger(0, vTag, OBJPROP_COLOR, valColor);}
void RenderLiveHeaderLabel(string tag, string c1, string c2, string c3, string c4, int x, int y) {string fullTag = "UKB_HDR_" + tag;if(ObjectFind(0, fullTag) < 0) { CChartObjectLabel l; l.Create(0, fullTag, 0, x, y); l.Font("Consolas"); l.FontSize(9); l.Color(InpTextMuted); l.Detach(); } string format = StringFormat("%-9s %-7s %-7s %-7s", c1, c2, c3, c4);ObjectSetString(0, fullTag, OBJPROP_TEXT, format);}
void RenderGridRow(string tag, string asset, string bid, string ask, string spread, int x, int y, color spreadCol) {string t1 = "UKB_G1_" + tag; string t2 = "UKB_G2_" + tag; string t3 = "UKB_G3_" + tag; string t4 = "UKB_G4_" + tag;if(ObjectFind(0, t1) < 0) { CChartObjectLabel l; l.Create(0, t1, 0, x, y); l.Font("Segoe UI Semibold"); l.FontSize(9); l.Color(InpTextMain); l.Detach(); } ObjectSetString(0, t1, OBJPROP_TEXT, asset);if(ObjectFind(0, t2) < 0) { CChartObjectLabel l; l.Create(0, t2, 0, x + 65, y); l.Font("Consolas"); l.FontSize(10); l.Color(InpTextMain); l.Detach(); } ObjectSetString(0, t2, OBJPROP_TEXT, bid);if(ObjectFind(0, t3) < 0) { CChartObjectLabel l; l.Create(0, t3, 0, x + 125, y); l.Font("Consolas"); l.FontSize(10); l.Color(InpTextMain); l.Detach(); } ObjectSetString(0, t3, OBJPROP_TEXT, ask);if(ObjectFind(0, t4) < 0) { CChartObjectLabel l; l.Create(0, t4, 0, x + 190, y); l.Font("Consolas"); l.FontSize(10); l.Detach(); } ObjectSetString(0, t4, OBJPROP_TEXT, spread);ObjectSetInteger(0, t4, OBJPROP_COLOR, spreadCol);}
void RenderMatrixRow(string tag, string asset, string tf1, string tf2, string tf3, int x, int y, color c1, color c2, color c3) {string t1 = "UKB_M1_" + tag; string t2 = "UKB_M2_" + tag; string t3 = "UKB_M3_" + tag; string t4 = "UKB_M4_" + tag;if(ObjectFind(0, t1) < 0) { CChartObjectLabel l; l.Create(0, t1, 0, x, y); l.Font("Segoe UI Semibold"); l.FontSize(9); l.Color(InpTextMain); l.Detach(); } ObjectSetString(0, t1, OBJPROP_TEXT, asset);if(ObjectFind(0, t2) < 0) { CChartObjectLabel l; l.Create(0, t2, 0, x + 65, y); l.Font("Consolas"); l.FontSize(9); l.Detach(); } ObjectSetString(0, t2, OBJPROP_TEXT, tf1); ObjectSetInteger(0, t2, OBJPROP_COLOR, c1);if(ObjectFind(0, t3) < 0) { CChartObjectLabel l; l.Create(0, t3, 0, x + 125, y); l.Font("Consolas"); l.FontSize(9); l.Detach(); } ObjectSetString(0, t3, OBJPROP_TEXT, tf2); ObjectSetInteger(0, t3, OBJPROP_COLOR, c2);if(ObjectFind(0, t4) < 0) { CChartObjectLabel l; l.Create(0, t4, 0, x + 190, y); l.Font("Consolas"); l.FontSize(9); l.Detach(); } ObjectSetString(0, t4, OBJPROP_TEXT, tf3); ObjectSetInteger(0, t4, OBJPROP_COLOR, c3);}
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
