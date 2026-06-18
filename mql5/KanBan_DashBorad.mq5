//+------------------------------------------------------------------+
//|                                              KanbanDashboard.mq5 |
//|                                  Copyright 2026, Trading Systems |
//|                                             https://mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      "https://mql5.com"
#property version   "1.00"
#property description "Live Kanban-Style Trading Dashboard Interface"
#property indicator_chart_window

//--- Input Parameters for UI Customization
input group "--- UI Theme Configuration ---"
input color InpBgColor      = C'22,26,30';     // Dashboard Panel Background
input color InpCardColor    = C'29,35,41';     // Column/Card Background
input color InpTextColor    = C'200,205,210';  // Default Text Color
input color InpAccentGreen  = C'40,167,69';    // Positive / Bullish Accent
input color InpAccentRed    = C'220,53,69';    // Negative / Bearish Accent

//--- Global Variables for Layout Math
int totalColumns = 5;
int colWidth     = 230;
int colGap       = 15;
int panelTop     = 50;
int cardHeight   = 450;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   //--- Clear any existing charts artifacts to avoid layout overlap
   ObjectsDeleteAll(0, "KB_");
   
   //--- Render the main background canvas
   CreateBackground();

   //--- Define column titles mimicking our Kanban system
   string columns[5] = {
      "1. ACCOUNT & RISK", 
      "2. MARKET WATCH", 
      "3. TECHNICAL TRENDS", 
      "4. ACTIVE TRADES", 
      "5. FUNDAMENTALS"
   };

   //--- Loop through and draw each Kanban Column container
   for(int i=0; i<totalColumns; i++)
     {
      int xPos = 20 + i * (colWidth + colGap);
      CreateColumnContainer(columns[i], "KB_COL_" + IntegerToString(i), xPos, panelTop);
     }

   //--- Trigger initial live data draw
   RefreshDashboardData();
   ChartRedraw(0);
   
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   //--- Clean up all UI objects from chart window on removal
   ObjectsDeleteAll(0, "KB_");
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| Expert tick function (Executes on every live market quote)       |
//+------------------------------------------------------------------+
void OnTick()
  {
   //--- Update Account and Live Position columns continuously
   RefreshDashboardData();
  }

//+------------------------------------------------------------------+
//| Core Function: Create Main Interface Canvas                      |
//+------------------------------------------------------------------+
void CreateBackground()
  {
   string name = "KB_MAIN_BG";
   ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 0);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 0);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, 2000); // Dynamic width stretch
   ObjectSetInteger(0, name, OBJPROP_YSIZE, 1080); // Dynamic height stretch
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, InpBgColor);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_BACK, true); // Keep behind market bars
  }

//+------------------------------------------------------------------+
//| Core Function: Create Indivual Column Panels                      |
//+------------------------------------------------------------------+
void CreateColumnContainer(string headerText, string objPrefix, int x, int y)
  {
   // 1. Draw Column Outer Box
   string bgName = objPrefix + "_BG";
   ObjectCreate(0, bgName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bgName, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, bgName, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, bgName, OBJPROP_XSIZE, colWidth);
   ObjectSetInteger(0, bgName, OBJPROP_YSIZE, cardHeight);
   ObjectSetInteger(0, bgName, OBJPROP_BGCOLOR, InpCardColor);
   ObjectSetInteger(0, bgName, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   
   // 2. Draw Column Header Label
   string textName = objPrefix + "_TXT";
   ObjectCreate(0, textName, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, textName, OBJPROP_XDISTANCE, x + 10);
   ObjectSetInteger(0, textName, OBJPROP_YDISTANCE, y + 10);
   ObjectSetString(0, textName, OBJPROP_TEXT, headerText);
   ObjectSetString(0, textName, OBJPROP_FONT, "Segoe UI Semibold");
   ObjectSetInteger(0, textName, OBJPROP_FONTSIZE, 11);
   ObjectSetInteger(0, textName, OBJPROP_COLOR, InpTextColor);
  }

//+------------------------------------------------------------------+
//| Core Function: Update Metrics dynamically                       |
//+------------------------------------------------------------------+
void RefreshDashboardData()
  {
   //--- Calculate current live production metrics
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double profit   = AccountInfoDouble(ACCOUNT_PROFIT);
   double marginLvl = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   
   //--- Position coordinates for data fields in Column 1 (Account & Risk)
   int startX = 30;
   int startY = panelTop + 45;
   int lineSpacing = 30;

   UpdateLiveLabel("KB_VAL_BAL", "Balance:  $" + DoubleToString(balance, 2), startX, startY, InpTextColor);
   UpdateLiveLabel("KB_VAL_EQT", "Equity:   $" + DoubleToString(equity, 2), startX, startY + lineSpacing, InpTextColor);
   
   // Colorize live floating profit dynamically based on performance status
   color profitColor = (profit >= 0) ? InpAccentGreen : InpAccentRed;
   UpdateLiveLabel("KB_VAL_PRF", "Float P/L: $" + DoubleToString(profit, 2), startX, startY + (lineSpacing * 2), profitColor);
   
   UpdateLiveLabel("KB_VAL_MAR", "Margin Lvl: " + DoubleToString(marginLvl, 1) + "%", startX, startY + (lineSpacing * 3), InpAccentGreen);
  }

//+------------------------------------------------------------------+
//| Helper Function: Efficiently create or update dynamic text strings|
//+------------------------------------------------------------------+
void UpdateLiveLabel(string name, string text, int x, int y, color textCol)
  {
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas"); // Fixed-width font for aligned data grids
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
   ObjectSetInteger(0, name, OBJPROP_COLOR, textCol);
  }
