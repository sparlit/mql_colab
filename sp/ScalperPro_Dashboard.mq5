//+------------------------------------------------------------------+
//|                                          ScalperPro_Dashboard.mq5 |
//|                          Scalper Pro — Kanban Dashboard            |
//|                          Multi-column layout with all data         |
//+------------------------------------------------------------------+
#property copyright "Scalper Pro"
#property version   "12.00"
#property strict

#include <Trade/Trade.mqh>

//--- Input parameters
input string   InpDataPath    = "brain_data\\";
input int      InpRefreshMs   = 1000;
input color    InpBgColor     = C'10,14,23';
input color    InpHeaderColor = C'0,180,255';
input color    InpGreenColor  = C'0,255,136';
input color    InpRedColor    = C'255,68,68';
input color    InpYellowColor = C'251,191,36';
input color    InpTextColor   = C'200,200,200';
input color    InpDimColor    = C'100,100,100';
input color    InpBarBg       = C'30,30,40';
input color    InpBarFill     = C'0,180,255';
input color    InpColBg       = C'15,18,28';
input color    InpColBorder   = C'40,60,90';

//--- Kanban dimensions
#define PANEL_X      5
#define PANEL_Y      25
#define COL_COUNT    3
#define COL_WIDTH    400
#define COL_GAP      8
#define CARD_PAD     4
#define LINE_H       13
#define BAR_H        6
#define CARD_GAP     8

//--- Global variables
datetime lastRefresh = 0;
string dataFile = "", posFile = "", symFile = "";

//--- Data
struct BrainData {
   double balance, equity, margin, marginFree, profit;
   double drawdown, winRate, profitFactor, sharpe, expectancy, kelly;
   int    totalTrades, openTrades, maxTrades, dailyTrades, maxDailyTrades;
   double dailyPnl, confidence, healthScore, cpuUsage, memUsage;
   int    errorCount, analysisCount, skipCount;
   double avgSpread;
   string regime, session, consensus, lastDirection, circuitBreaker;
   double scanProgress, analysisProgress, tradeProgress;
   int    activeThreads, poolWorkers, symbolsAnalyzed;
   string currentAction, lastScanTime;
   string v11Method;
   double v11ConfigSl, v11ConfigTp, v11ConfigRisk;
   string server, company, accountName;
   int    login;
   double marginLevel, credit;
   string currentSymbol;
   double currentBid, currentAsk;
   int    currentSpread, currentDigits;
   double currentPoint, currentVolumeMin, currentVolumeMax;
   double currentSwapLong, currentSwapShort, currentContractSize;
   double totalOpenProfit, totalOpenVolume;
   double memUsedGb, memTotalGb, diskFreeGb, diskUsagePct;
   int    cpuCount;
};
BrainData bd;

//+------------------------------------------------------------------+
int OnInit()
{
   dataFile = InpDataPath + "mt5_dashboard.json";
   posFile = InpDataPath + "mt5_positions.json";
   symFile = InpDataPath + "mt5_symbols.json";
   CreatePanel(3 * COL_WIDTH + 2 * COL_GAP);
   EventSetMillisecondTimer(InpRefreshMs);
   Print("=== SCALPER PRO KANBAN DASHBOARD v12 ===");
   Print("  Symbol: ", Symbol(), " | TF: ", EnumToString((ENUM_TIMEFRAMES)Period()));
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); ObjectsDeleteAll(0, "SP_"); }
void OnTimer() { RefreshData(); DrawPanel(); }

//+------------------------------------------------------------------+
void RefreshData()
{
   datetime now = TimeCurrent();
   if(now - lastRefresh < InpRefreshMs / 1000) return;
   lastRefresh = now;
   string c = ReadFile(dataFile);
   if(StringLen(c) == 0) c = ReadFile("brain_data\\mt5_dashboard.json");
   if(StringLen(c) > 0) ParseBrainData(c);
}

string ReadFile(string fn)
{
   int h = FileOpen(fn, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE) h = FileOpen(fn, FILE_READ|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) return "";
   string c = "";
   while(!FileIsEnding(h)) c += FileReadString(h);
   FileClose(h);
   return c;
}

//+------------------------------------------------------------------+
void ParseBrainData(string j)
{
   bd.balance = D(j,"balance"); bd.equity = D(j,"equity"); bd.margin = D(j,"margin");
   bd.marginFree = D(j,"margin_free"); bd.profit = D(j,"profit");
   bd.drawdown = D(j,"drawdown"); bd.winRate = D(j,"win_rate");
   bd.profitFactor = D(j,"profit_factor"); bd.sharpe = D(j,"sharpe");
   bd.expectancy = D(j,"expectancy"); bd.kelly = D(j,"kelly");
   bd.totalTrades = (int)D(j,"total_trades"); bd.openTrades = (int)D(j,"open_trades");
   bd.maxTrades = (int)D(j,"max_trades"); bd.dailyTrades = (int)D(j,"daily_trades");
   bd.maxDailyTrades = (int)D(j,"max_daily_trades"); bd.dailyPnl = D(j,"daily_pnl");
   bd.confidence = D(j,"confidence"); bd.healthScore = D(j,"health_score");
   bd.cpuUsage = D(j,"cpu_overall"); bd.memUsage = D(j,"mem_percent");
   bd.errorCount = (int)D(j,"error_count"); bd.avgSpread = D(j,"avg_spread");
   bd.analysisCount = (int)D(j,"analysis_count"); bd.skipCount = (int)D(j,"skip_count");
   bd.regime = S(j,"regime"); bd.session = S(j,"session");
   bd.consensus = S(j,"consensus"); bd.lastDirection = S(j,"last_direction");
   bd.circuitBreaker = S(j,"circuit_breaker");
   bd.scanProgress = D(j,"scan_progress"); bd.analysisProgress = D(j,"analysis_progress");
   bd.tradeProgress = D(j,"trade_progress");
   bd.activeThreads = (int)D(j,"active_threads"); bd.poolWorkers = (int)D(j,"pool_workers");
   bd.symbolsAnalyzed = (int)D(j,"symbols_analyzed");
   bd.currentAction = S(j,"current_action"); bd.lastScanTime = S(j,"last_scan_time");
   bd.v11Method = S(j,"v11_method");
   bd.v11ConfigSl = D(j,"v11_config_sl"); bd.v11ConfigTp = D(j,"v11_config_tp");
   bd.v11ConfigRisk = D(j,"v11_config_risk");
   bd.server = S(j,"server"); bd.company = S(j,"company");
   bd.accountName = S(j,"name"); bd.login = (int)D(j,"login");
   bd.marginLevel = D(j,"margin_level"); bd.credit = D(j,"credit");
   bd.currentSymbol = S(j,"current_symbol"); bd.currentBid = D(j,"current_bid");
   bd.currentAsk = D(j,"current_ask"); bd.currentSpread = (int)D(j,"current_spread");
   bd.currentPoint = D(j,"current_point"); bd.currentDigits = (int)D(j,"current_digits");
   bd.totalOpenProfit = D(j,"total_open_profit"); bd.totalOpenVolume = D(j,"total_open_volume");
   bd.memUsedGb = D(j,"mem_used_gb"); bd.memTotalGb = D(j,"mem_total_gb");
   bd.diskFreeGb = D(j,"disk_free_gb"); bd.diskUsagePct = D(j,"disk_usage_pct");
   bd.cpuCount = (int)D(j,"cpu_count");
}

double D(string j, string k)
{
   string s = "\"" + k + "\":"; int p = StringFind(j, s);
   if(p < 0) return 0;
   string sub = StringSubstr(j, p + StringLen(s)); StringTrimLeft(sub);
   if(StringLen(sub) == 0) return 0;
   ushort ch = StringGetCharacter(sub, 0);
   if(ch == '"' || ch == 't' || ch == 'n') return 0;
   string n = "";
   for(int i = 0; i < MathMin(StringLen(sub), 30); i++)
   { ch = StringGetCharacter(sub, i); if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '+') n += ShortToString(ch); else if(StringLen(n) > 0) break; }
   return StringLen(n) > 0 ? StringToDouble(n) : 0;
}

string S(string j, string k)
{
   string s = "\"" + k + "\":\""; int p = StringFind(j, s);
   if(p < 0) return "";
   int st = p + StringLen(s); int en = StringFind(j, "\"", st);
   if(en < 0) return "";
   return StringSubstr(j, st, en - st);
}

//+------------------------------------------------------------------+
// KANBAN DRAW PANEL - 3 column layout
//+------------------------------------------------------------------+
void DrawPanel()
{
   int totalW = COL_COUNT * COL_WIDTH + (COL_COUNT - 1) * COL_GAP;
   CreatePanel(totalW);
   
   string sym = Symbol();
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   int spread = (int)SymbolInfoInteger(sym, SYMBOL_SPREAD);

   //=== HEADER BAR (full width) ===
   int hx = PANEL_X + 5, hy = PANEL_Y + 4;
   DrawLbl("HDR", hx, hy, "SCALPER PRO - " + sym + " | " + EnumToString((ENUM_TIMEFRAMES)Period()) + " | " + bd.v11Method, InpHeaderColor, 10, true);
   hy += LINE_H;
   DrawLbl("HDR2", hx, hy, StringFormat("Bid: %.5f | Ask: %.5f | Spread: %d pts | %s", bid, ask, spread, TimeToString(TimeCurrent(), TIME_SECONDS)), InpTextColor, 7, false);
   hy += LINE_H + 2;

   //=== COLUMN 1: ACCOUNT + PERFORMANCE ===
   int c1x = PANEL_X + CARD_PAD;
   int cy = hy;
   
   // Card: Health
   DrawCard("C1A", c1x, cy, COL_WIDTH - CARD_PAD*2, "SYSTEM HEALTH");
   cy += LINE_H + 2;
   string st = "RUNNING";
   color stc = InpGreenColor;
   if(bd.healthScore <= 50) { st = "WARNING"; stc = InpRedColor; }
   else if(bd.healthScore <= 80) { st = "DEGRADED"; stc = InpYellowColor; }
   DrawLbl("C1A1", c1x + 4, cy, StringFormat("%s | Health: %.0f%%", st, bd.healthScore), stc, 7, true);
   cy += LINE_H;
   DrawBar("C1AB", c1x + 4, cy, COL_WIDTH - CARD_PAD*2 - 8, bd.healthScore / 100.0, stc);
   cy += BAR_H + CARD_GAP;

   // Card: Account
   DrawCard("C1B", c1x, cy, COL_WIDTH - CARD_PAD*2, "ACCOUNT");
   cy += LINE_H + 2;
   DrawLbl("C1B1", c1x+4, cy, StringFormat("Balance: $%.2f", bd.balance), InpTextColor, 7, false);
   DrawLbl("C1B2", c1x+COL_WIDTH/2, cy, StringFormat("Equity: $%.2f", bd.equity), bd.equity >= bd.balance ? InpGreenColor : InpRedColor, 7, false);
   cy += LINE_H;
   DrawLbl("C1B3", c1x+4, cy, StringFormat("Profit: $%.2f | DD: %.1f%%", bd.profit, bd.drawdown), bd.profit >= 0 ? InpGreenColor : InpRedColor, 7, false);
   cy += LINE_H;
   DrawLbl("C1B4", c1x+4, cy, StringFormat("Margin: $%.2f | Free: $%.2f", bd.margin, bd.marginFree), InpTextColor, 7, false);
   cy += LINE_H + CARD_GAP;

   // Card: Performance
   DrawCard("C1C", c1x, cy, COL_WIDTH - CARD_PAD*2, "PERFORMANCE");
   cy += LINE_H + 2;
   DrawLbl("C1C1", c1x+4, cy, StringFormat("Win Rate: %.1f%%", bd.winRate), bd.winRate >= 50 ? InpGreenColor : InpRedColor, 7, false);
   cy += LINE_H;
   DrawBar("C1CB", c1x+4, cy, COL_WIDTH - CARD_PAD*2 - 8, bd.winRate / 100.0, bd.winRate >= 50 ? InpGreenColor : InpRedColor);
   cy += BAR_H;
   DrawLbl("C1C2", c1x+4, cy, StringFormat("PF: %.2f | Sharpe: %.2f | Kelly: %.1f%%", bd.profitFactor, bd.sharpe, bd.kelly*100), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C1C3", c1x+4, cy, StringFormat("Trades: %d | Open: %d/%d | Daily: %d/%d", bd.totalTrades, bd.openTrades, bd.maxTrades, bd.dailyTrades, bd.maxDailyTrades), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C1C4", c1x+4, cy, StringFormat("PnL: $%.2f | Exp: $%.2f", bd.dailyPnl, bd.expectancy), bd.dailyPnl >= 0 ? InpGreenColor : InpRedColor, 7, false);
   cy += LINE_H + CARD_GAP;

   // Card: Open Positions
   DrawCard("C1D", c1x, cy, COL_WIDTH - CARD_PAD*2, "POSITIONS");
   cy += LINE_H + 2;
   DrawLbl("C1D1", c1x+4, cy, StringFormat("Open: %d | Volume: %.2f | PnL: $%.2f", bd.openTrades, bd.totalOpenVolume, bd.totalOpenProfit), bd.totalOpenProfit >= 0 ? InpGreenColor : InpRedColor, 7, false);
   cy += BAR_H + CARD_GAP;

   //=== COLUMN 2: BRAIN STATUS + PROCESS ===
   int c2x = PANEL_X + COL_WIDTH + COL_GAP + CARD_PAD;
   cy = hy;
   
   // Card: Brain Status
   DrawCard("C2A", c2x, cy, COL_WIDTH - CARD_PAD*2, "BRAIN STATUS");
   cy += LINE_H + 2;
   DrawLbl("C2A1", c2x+4, cy, StringFormat("Regime: %s | Session: %s", bd.regime, bd.session), InpTextColor, 7, false);
   cy += LINE_H;
   color cc = bd.consensus == "BUY" ? InpGreenColor : bd.consensus == "SELL" ? InpRedColor : InpYellowColor;
   DrawLbl("C2A2", c2x+4, cy, StringFormat("Consensus: %s | Conf: %.0f%%", bd.consensus, bd.confidence*100), cc, 7, true);
   cy += LINE_H;
   DrawLbl("C2A3", c2x+4, cy, StringFormat("Direction: %s | Circuit: %s", bd.lastDirection, bd.circuitBreaker), bd.circuitBreaker == "CLOSED" ? InpGreenColor : InpRedColor, 7, false);
   cy += LINE_H;
   DrawLbl("C2A4", c2x+4, cy, StringFormat("Method: %s | SL: %.1fx | TP: %.1fx | Risk: %.1f%%", bd.v11Method, bd.v11ConfigSl, bd.v11ConfigTp, bd.v11ConfigRisk), InpYellowColor, 7, false);
   cy += LINE_H + CARD_GAP;

   // Card: Process Status
   DrawCard("C2B", c2x, cy, COL_WIDTH - CARD_PAD*2, "PROCESS STATUS");
   cy += LINE_H + 2;
   DrawLbl("C2B1", c2x+4, cy, StringFormat("Threads: %d | Pool: %d | Symbols: %d", bd.activeThreads, bd.poolWorkers, bd.symbolsAnalyzed), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C2B2", c2x+4, cy, StringFormat("Action: %s | Last: %s", bd.currentAction, bd.lastScanTime), InpYellowColor, 7, false);
   cy += LINE_H;
   DrawLbl("C2B3", c2x+4, cy, "Scan", InpTextColor, 6, false);
   DrawBar("C2B3", c2x+35, cy, COL_WIDTH - CARD_PAD*2 - 80, bd.scanProgress/100.0, InpBarFill);
   DrawLbl("C2B3v", c2x+COL_WIDTH-CARD_PAD*2-10, cy, StringFormat("%.0f%%", bd.scanProgress), InpDimColor, 6, false);
   cy += LINE_H;
   DrawLbl("C2B4", c2x+4, cy, "Analysis", InpTextColor, 6, false);
   DrawBar("C2B4", c2x+35, cy, COL_WIDTH - CARD_PAD*2 - 80, bd.analysisProgress/100.0, C'0,200,100');
   DrawLbl("C2B4v", c2x+COL_WIDTH-CARD_PAD*2-10, cy, StringFormat("%.0f%%", bd.analysisProgress), InpDimColor, 6, false);
   cy += LINE_H;
   DrawLbl("C2B5", c2x+4, cy, "Trade", InpTextColor, 6, false);
   DrawBar("C2B5", c2x+35, cy, COL_WIDTH - CARD_PAD*2 - 80, bd.tradeProgress/100.0, C'255,160,0');
   DrawLbl("C2B5v", c2x+COL_WIDTH-CARD_PAD*2-10, cy, StringFormat("%.0f%%", bd.tradeProgress), InpDimColor, 6, false);
   cy += LINE_H + CARD_GAP;

   // Card: System Resources
   DrawCard("C2C", c2x, cy, COL_WIDTH - CARD_PAD*2, "SYSTEM RESOURCES");
   cy += LINE_H + 2;
   DrawLbl("C2C1", c2x+4, cy, "CPU", InpTextColor, 6, false);
   DrawBar("C2C1", c2x+30, cy, COL_WIDTH - CARD_PAD*2 - 70, bd.cpuUsage/100.0, bd.cpuUsage < 60 ? InpGreenColor : bd.cpuUsage < 85 ? InpYellowColor : InpRedColor);
   DrawLbl("C2C1v", c2x+COL_WIDTH-CARD_PAD*2-10, cy, StringFormat("%.0f%%", bd.cpuUsage), InpDimColor, 6, false);
   cy += LINE_H;
   DrawLbl("C2C2", c2x+4, cy, "MEM", InpTextColor, 6, false);
   DrawBar("C2C2", c2x+30, cy, COL_WIDTH - CARD_PAD*2 - 70, bd.memUsage/100.0, bd.memUsage < 60 ? InpGreenColor : bd.memUsage < 85 ? InpYellowColor : InpRedColor);
   DrawLbl("C2C2v", c2x+COL_WIDTH-CARD_PAD*2-10, cy, StringFormat("%.0f%%", bd.memUsage), InpDimColor, 6, false);
   cy += LINE_H;
   DrawLbl("C2C3", c2x+4, cy, StringFormat("CPU: %d cores | MEM: %.1f/%.1f GB", bd.cpuCount, bd.memUsedGb, bd.memTotalGb), InpDimColor, 6, false);
   cy += LINE_H;
   DrawLbl("C2C4", c2x+4, cy, StringFormat("Disk: %.1f GB free | Errors: %d | Spread: %.1f", bd.diskFreeGb, bd.errorCount, bd.avgSpread), InpDimColor, 6, false);
   cy += LINE_H + CARD_GAP;

   // Card: Account Details
   DrawCard("C2D", c2x, cy, COL_WIDTH - CARD_PAD*2, "ACCOUNT INFO");
   cy += LINE_H + 2;
   DrawLbl("C2D1", c2x+4, cy, StringFormat("Server: %s | Login: %d", bd.server, bd.login), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C2D2", c2x+4, cy, StringFormat("Leverage: 1:%d | Margin Level: %.0f%%", (int)D(dataFile, "leverage") > 0 ? (int)D(dataFile, "leverage") : 200, bd.marginLevel), InpTextColor, 7, false);

   //=== COLUMN 3: MTF TRENDS + SYMBOL ===
   int c3x = PANEL_X + 2*COL_WIDTH + 2*COL_GAP + CARD_PAD;
   cy = hy;
   
   // Card: Multi-Timeframe Trends
   DrawCard("C3A", c3x, cy, COL_WIDTH - CARD_PAD*2, "MULTI-TIMEFRAME TRENDS");
   cy += LINE_H + 2;
   string tfn[]; ArrayResize(tfn, 8);
   tfn[0]="M1"; tfn[1]="M5"; tfn[2]="M15"; tfn[3]="M30";
   tfn[4]="H1"; tfn[5]="H4"; tfn[6]="D1"; tfn[7]="W1";
   for(int i = 0; i < 8; i++)
   {
      DrawLbl("C3A" + IntegerToString(i), c3x+4, cy + i*LINE_H, StringFormat("%s: ---", tfn[i]), InpDimColor, 7, false);
   }
   cy += 8*LINE_H + CARD_GAP;

   // Card: Symbol Details
   DrawCard("C3B", c3x, cy, COL_WIDTH - CARD_PAD*2, "SYMBOL: " + bd.currentSymbol);
   cy += LINE_H + 2;
   DrawLbl("C3B1", c3x+4, cy, StringFormat("Bid: %.5f | Ask: %.5f | Spread: %d", bd.currentBid, bd.currentAsk, bd.currentSpread), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C3B2", c3x+4, cy, StringFormat("Point: %.5f | Digits: %d | Contract: %.0f", bd.currentPoint, bd.currentDigits, bd.currentContractSize), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C3B3", c3x+4, cy, StringFormat("Swap L: %.1f | Swap S: %.1f", bd.currentSwapLong, bd.currentSwapShort), InpTextColor, 7, false);
   cy += LINE_H + CARD_GAP;

   // Card: Strategy Performance
   DrawCard("C3C", c3x, cy, COL_WIDTH - CARD_PAD*2, "STRATEGY");
   cy += LINE_H + 2;
   DrawLbl("C3C1", c3x+4, cy, StringFormat("Expectancy: $%.2f", bd.expectancy), bd.expectancy >= 0 ? InpGreenColor : InpRedColor, 7, false);
   cy += LINE_H;
   DrawLbl("C3C2", c3x+4, cy, StringFormat("Analysis: %d | Skips: %d | Avg Spread: %.1f", bd.analysisCount, bd.skipCount, bd.avgSpread), InpTextColor, 7, false);
   cy += LINE_H;
   DrawLbl("C3C3", c3x+4, cy, StringFormat("Confidence: %.0f%% | Trades Today: %d", bd.confidence*100, bd.dailyTrades), InpTextColor, 7, false);
}

//+------------------------------------------------------------------+
void DrawCard(string id, int x, int y, int w, string title)
{
   string n = "SP_BG_" + id;
   ObjectCreate(0, n, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, n, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, n, OBJPROP_YSIZE, LINE_H * 6 + CARD_PAD * 2);
   ObjectSetInteger(0, n, OBJPROP_BGCOLOR, InpColBg);
   ObjectSetInteger(0, n, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, n, OBJPROP_COLOR, InpColBorder);
   ObjectSetInteger(0, n, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
   DrawLbl("CT_" + id, x + 4, y + 2, title, InpHeaderColor, 7, true);
}

void DrawLbl(string id, int x, int y, string text, color clr, int sz, bool bold)
{
   string n = "SP_" + id;
   ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetString(0, n, OBJPROP_TEXT, text);
   ObjectSetString(0, n, OBJPROP_FONT, bold ? "Consolas Bold" : "Consolas");
   ObjectSetInteger(0, n, OBJPROP_FONTSIZE, sz);
   ObjectSetInteger(0, n, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
}

void DrawBar(string id, int x, int y, int width, double pct, color fillClr)
{
   pct = MathMax(0, MathMin(1, pct));
   string bg = "SP_BAR_" + id; string fl = "SP_BARF_" + id;
   ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE, width);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE, BAR_H);
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, InpBarBg);
   ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, bg, OBJPROP_COLOR, InpBarBg);
   ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
   int fw = (int)(width * pct);
   ObjectCreate(0, fl, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, fl, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, fl, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, fl, OBJPROP_XSIZE, MathMax(fw, 1));
   ObjectSetInteger(0, fl, OBJPROP_YSIZE, BAR_H);
   ObjectSetInteger(0, fl, OBJPROP_BGCOLOR, fillClr);
   ObjectSetInteger(0, fl, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, fl, OBJPROP_COLOR, fillClr);
   ObjectSetInteger(0, fl, OBJPROP_SELECTABLE, false);
}

void CreatePanel(int totalWidth)
{
   string n = "SP_BG";
   ObjectCreate(0, n, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, PANEL_X);
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, PANEL_Y);
   ObjectSetInteger(0, n, OBJPROP_XSIZE, totalWidth + 10);
   ObjectSetInteger(0, n, OBJPROP_YSIZE, 520);
   ObjectSetInteger(0, n, OBJPROP_BGCOLOR, InpBgColor);
   ObjectSetInteger(0, n, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, n, OBJPROP_COLOR, C'30,58,95');
   ObjectSetInteger(0, n, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
}
//+------------------------------------------------------------------+
