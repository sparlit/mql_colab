//+------------------------------------------------------------------+
//|                                          ScalperPro_Dashboard.mq5 |
//|                          Scalper Pro — Kanban Dashboard v13        |
//|                          Complete trading dashboard                |
//+------------------------------------------------------------------+
#property copyright "Scalper Pro"
#property version   "13.00"
#property strict

#include <Trade/Trade.mqh>

//--- Input parameters
input string InpDataPath  = "brain_data\\";
input int    InpRefreshMs = 1000;
input color  InpBg        = C'10,14,23';
input color  InpHdr       = C'0,180,255';
input color  InpGreen     = C'0,255,136';
input color  InpRed       = C'255,68,68';
input color  InpYellow    = C'251,191,36';
input color  InpText      = C'200,200,200';
input color  InpDim       = C'100,100,100';
input color  InpBarBg     = C'30,30,40';
input color  InpBarFill   = C'0,180,255';
input color  InpColBg     = C'15,18,28';
input color  InpColBr     = C'40,60,90';
input bool   InpAutoTF    = true;

//--- Layout
#define PX 5
#define PY 25
#define CW 410
#define CG 10
#define CP 4
#define LH 15
#define BH 6
#define CGP 4

//--- Globals
datetime lastRefresh = 0;
string dataFile = "", posFile = "", symFile = "";
string settingsFile = "";

//--- Settings from database
int    SET_refresh_ms = 1000;
bool   SET_auto_tf = true;
int    SET_max_positions = 3;
double SET_max_risk = 1.0;
double SET_sl_atr_mult = 1.5;
double SET_tp_atr_mult = 2.5;
int    SET_max_spread = 50;
double SET_trail_start = 30;
double SET_trail_step = 10;
double SET_break_even = 20;
int    SET_font_header = 12;
int    SET_font_regular = 9;
int    SET_font_small = 8;

//--- Data
struct D {
   double bal,eq,mgn,mgnF,prof;
   double dd,wr,pf,sh,exp,kl;
   int    tt,ot,mt,dt,mdt;
   double dp,conf,hs,cpu,mem;
   int    ec,ac,sc;
   double as;
   string rg,se,co,ld,cb;
   double sp,ap,tp;
   int    at,pw,sa;
   string ca,lt;
   string vm,cs,ct,cr;
   double cv,cl,cty;
   string sv,co2,an;
   int    lg;
   double ml,cr2;
   string cs2;
   double cb2,ca2;
   int    cs3,cd;
   double cp2,cvm,cvs,csl,css;
   double top,tov;
   double mu,mt2,df,dp2;
   int    cc;
   double rsi,macd,ms,mh;
   string mc;
   double sk,sd,e20,e50,e200;
   double atr2,bu,bl,bw;
   string ne,ei,ec2;
   double sl,ss;
   string cg2;
   // Kanban
   string kb_ideas, kb_valid, kb_active, kb_review;
   // Session & Clock
   string sess, sess_st, sess_col, sess_utc, sess_local;
   string next_sess, next_in;
   // MTF Timers
   string tmr[7];
   double tmr_p[7];
};

D d;

//+------------------------------------------------------------------+
//| Helper: Read file contents                                        |
//+------------------------------------------------------------------+
string ReadFile(string filename)
{
   int handle = FileOpen(filename, FILE_READ | FILE_TXT | FILE_COMMON);
   if(handle == INVALID_HANDLE) return "";
   string content = "";
   while(!FileIsEnding(handle))
   {
      content += FileReadString(handle);
   }
   FileClose(handle);
   return content;
}

//+------------------------------------------------------------------+
//| Helper: Extract double from JSON                                  |
//+------------------------------------------------------------------+
double JsonDbl(string json, string key)
{
   return JD(json, key);
}

//+------------------------------------------------------------------+
//| Helper: Extract string from JSON                                  |
//+------------------------------------------------------------------+
string JsonStr(string json, string key)
{
   return JS(json, key);
}

//+------------------------------------------------------------------+
//| Load settings from JSON database                                  |
//+------------------------------------------------------------------+
void LoadSettings()
{
   settingsFile = InpDataPath + "dashboard_settings.json";
   string content = ReadFile(settingsFile);
   if(StringLen(content) == 0)
      content = ReadFile("brain_data\\dashboard_settings.json");
   if(StringLen(content) == 0) return;

   // Parse settings
   SET_refresh_ms = (int)JsonDbl(content, "refresh_ms");
   SET_auto_tf = JsonDbl(content, "auto_tf") > 0;
   SET_max_positions = (int)JsonDbl(content, "max_positions");
   SET_max_risk = JsonDbl(content, "max_risk_per_trade");
   SET_sl_atr_mult = JsonDbl(content, "sl_atr_mult");
   SET_tp_atr_mult = JsonDbl(content, "tp_atr_mult");
   SET_max_spread = (int)JsonDbl(content, "max_spread_points");
   SET_trail_start = JsonDbl(content, "trail_start_pips");
   SET_trail_step = JsonDbl(content, "trail_step_pips");
   SET_break_even = JsonDbl(content, "break_even_pips");
   SET_font_header = (int)JsonDbl(content, "font_size_header");
   SET_font_regular = (int)JsonDbl(content, "font_size_regular");
   SET_font_small = (int)JsonDbl(content, "font_size_small");

   Print("Settings loaded: Refresh=", SET_refresh_ms, "ms, MaxRisk=", SET_max_risk, "%");
}

//+------------------------------------------------------------------+
int OnInit()
{
   dataFile = InpDataPath + "mt5_dashboard.json";
   posFile = InpDataPath + "mt5_positions.json";
   symFile = InpDataPath + "mt5_symbols.json";
   
   // Load settings from database
   LoadSettings();
   
   CreatePanel(3 * CW + 2 * CG);
   EventSetMillisecondTimer(SET_refresh_ms);
   Print("=== AUTONOMOUS FOREX AUTOTRADER KANBAN v13 ===");
   Print("  ", Symbol(), " | ", EnumToString((ENUM_TIMEFRAMES)Period()));
   Print("  Settings: Refresh=", SET_refresh_ms, "ms | Risk=", SET_max_risk, "% | Spread=", SET_max_spread);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int r) { EventKillTimer(); ObjectsDeleteAll(0, "S_"); }
void OnTimer() { Refresh(); Draw(); }

//+------------------------------------------------------------------+
void Refresh()
{
   datetime now = TimeCurrent();
   if(now - lastRefresh < InpRefreshMs / 1000) return;
   lastRefresh = now;
   string c = Read(dataFile);
   if(StringLen(c) == 0) c = Read("brain_data\\mt5_dashboard.json");
   if(StringLen(c) > 0) Parse(c);
}

string Read(string fn)
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
void Parse(string j)
{
   d.bal=JD(j,"balance"); d.eq=JD(j,"equity"); d.mgn=JD(j,"margin");
   d.mgnF=JD(j,"margin_free"); d.prof=JD(j,"profit"); d.dd=JD(j,"drawdown");
   d.wr=JD(j,"win_rate"); d.pf=JD(j,"profit_factor"); d.sh=JD(j,"sharpe");
   d.exp=JD(j,"expectancy"); d.kl=JD(j,"kelly");
   d.tt=(int)JD(j,"total_trades"); d.ot=(int)JD(j,"open_trades");
   d.mt=(int)JD(j,"max_trades"); d.dt=(int)JD(j,"daily_trades");
   d.mdt=(int)JD(j,"max_daily_trades"); d.dp=JD(j,"daily_pnl");
   d.conf=JD(j,"confidence"); d.hs=JD(j,"health_score");
   d.cpu=JD(j,"cpu_overall"); d.mem=JD(j,"mem_percent");
   d.ec=(int)JD(j,"error_count"); d.as=JD(j,"avg_spread");
   d.ac=(int)JD(j,"analysis_count"); d.sc=(int)JD(j,"skip_count");
   d.rg=JS(j,"regime"); d.se=JS(j,"session"); d.co=JS(j,"consensus");
   d.ld=JS(j,"last_direction"); d.cb=JS(j,"circuit_breaker");
   d.sp=JD(j,"scan_progress"); d.ap=JD(j,"analysis_progress");
   d.tp=JD(j,"trade_progress");
   d.at=(int)JD(j,"active_threads"); d.pw=(int)JD(j,"pool_workers");
   d.sa=(int)JD(j,"symbols_analyzed");
   d.ca=JS(j,"current_action"); d.lt=JS(j,"last_scan_time");
   d.vm=JS(j,"v11_method");
   d.cv=JD(j,"v11_config_sl"); d.ct=JD(j,"v11_config_tp");
   d.cr=JD(j,"v11_config_risk");
   d.sv=JS(j,"server"); d.an=JS(j,"name");
   d.lg=(int)JD(j,"login"); d.ml=JD(j,"margin_level");
   d.cr2=JD(j,"credit"); d.cs2=JS(j,"current_symbol");
   d.cb2=JD(j,"current_bid"); d.ca2=JD(j,"current_ask");
   d.cs3=(int)JD(j,"current_spread"); d.cd=(int)JD(j,"current_digits");
   d.cp2=JD(j,"current_point");
   d.top=JD(j,"total_open_profit"); d.tov=JD(j,"total_open_volume");
   d.mu=JD(j,"mem_used_gb"); d.mt2=JD(j,"mem_total_gb");
   d.df=JD(j,"disk_free_gb"); d.dp2=JD(j,"disk_usage_pct");
   d.cc=(int)JD(j,"cpu_count");
   // Technical
   d.rsi=JD(j,"rsi"); d.macd=JD(j,"macd"); d.ms=JD(j,"macd_signal");
   d.mh=JD(j,"macd_hist"); d.mc=JS(j,"macd_cross");
   d.sk=JD(j,"stoch_k"); d.sd=JD(j,"stoch_d");
   d.e20=JD(j,"ema20"); d.e50=JD(j,"ema50"); d.e200=JD(j,"ema200");
   d.atr2=JD(j,"atr"); d.bu=JD(j,"bb_upper"); d.bl=JD(j,"bb_lower");
   d.bw=JD(j,"bb_width");
   // Macro
   d.ne=JS(j,"next_event"); d.ei=JS(j,"event_impact"); d.ec2=JS(j,"event_countdown");
   d.sl=JD(j,"sentiment_long"); d.ss=JD(j,"sentiment_short");
   // Kanban
   d.kb_ideas=JS(j,"kb_ideas"); d.kb_valid=JS(j,"kb_valid");
   d.kb_active=JS(j,"kb_active"); d.kb_review=JS(j,"kb_review");
   // Session & Clock
   d.sess=JS(j,"session"); d.sess_st=JS(j,"session_status");
   d.sess_col=JS(j,"session_color"); d.sess_utc=JS(j,"session_utc");
   d.sess_local=JS(j,"session_local");
   d.next_sess=JS(j,"next_session"); d.next_in=JS(j,"next_session_in");
   // MTF Timers
   for(int i=0;i<7;i++)
   {
      string t[]; ArrayResize(t,7);
      t[0]="M1";t[1]="M5";t[2]="M15";t[3]="M30";t[4]="H1";t[5]="H4";t[6]="D1";
      d.tmr[i]=JS(j,"timer_"+t[i]);
      d.tmr_p[i]=JD(j,"timer_"+t[i]+"_pct");
   }
}

double JD(string j, string k)
{
   string s="\""+k+"\":"; int p=StringFind(j,s);
   if(p<0) return 0;
   string sub=StringSubstr(j,p+StringLen(s)); StringTrimLeft(sub);
   if(StringLen(sub)==0) return 0;
   ushort ch=StringGetCharacter(sub,0);
   if(ch=='"'||ch=='t'||ch=='n') return 0;
   string n="";
   for(int i=0;i<MathMin(StringLen(sub),30);i++)
   { ch=StringGetCharacter(sub,i); if((ch>='0'&&ch<='9')||ch=='.'||ch=='-'||ch=='+') n+=ShortToString(ch); else if(StringLen(n)>0) break; }
   return StringLen(n)>0?StringToDouble(n):0;
}

string JS(string j, string k)
{
   string s="\""+k+"\":\""; int p=StringFind(j,s);
   if(p<0) return "";
   int st=p+StringLen(s); int en=StringFind(j,"\"",st);
   if(en<0) return "";
   return StringSubstr(j,st,en-st);
}

//+------------------------------------------------------------------+
void Draw()
{
   int tw=3*CW+2*CG;
   CreatePanel(tw);
   string sym=Symbol();
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   int spr=(int)SymbolInfoInteger(sym,SYMBOL_SPREAD);

   //=== HEADER ===
   int hx=PX+5, hy=PY+4;
   DrawL("HDR",hx,hy,"AUTONOMOUS FOREX AUTOTRADER - "+sym+" | "+EnumToString((ENUM_TIMEFRAMES)Period())+" | "+d.vm,InpHdr,12,true);
   hy+=LH;
   DrawL("HDR2",hx,hy,StringFormat("Bid: %.5f | Ask: %.5f | Spread: %d pts",bid,ask,spr),InpText,9,false);
   hy+=LH;
   DrawL("HDR3",hx,hy,StringFormat("Clock: %s UTC | %s Local | Session: %s [%s]",d.sess_utc,d.sess_local,d.sess,d.sess_st),InpText,9,false);
   hy+=LH;
   DrawL("HDR4",hx,hy,StringFormat("Next: %s in %s",d.next_sess,d.next_in),InpYellow,9,false);
   hy+=LH+2;

   //=== COL 1: ACCOUNT + RISK ===
   int c1=PX+CP; int cy=hy;

   // Card: Balance & Equity
   DrawC("C1A",c1,cy,CW-CP*2,"ACCOUNT & RISK");
   cy+=LH+2;
   DrawL("C1A1",c1+4,cy,StringFormat("Balance: $%.2f",d.bal),InpText,9,false);
   DrawL("C1A2",c1+CW/2,cy,StringFormat("Equity: $%.2f",d.eq),d.eq>=d.bal?InpGreen:InpRed,9,false);
   cy+=LH;
   DrawL("C1A3",c1+4,cy,StringFormat("Margin: $%.2f | Free: $%.2f",d.mgn,d.mgnF),InpText,9,false);
   cy+=LH;
   DrawL("C1A4",c1+4,cy,StringFormat("Margin Level: %.0f%% | Leverage: 1:%d",d.ml,(int)JD(dataFile,"leverage")),InpText,9,false);
   cy+=LH;
   DrawL("C1A5",c1+4,cy,StringFormat("Profit: $%.2f | DD: %.1f%%",d.prof,d.dd),d.prof>=0?InpGreen:InpRed,9,false);
   cy+=LH;
   DrawL("C1A6",c1+4,cy,StringFormat("Daily PnL: $%.2f | Credit: $%.2f",d.dp,d.cr2),InpText,9,false);
   cy+=LH+CGP;

   // Card: Performance
   DrawC("C1B",c1,cy,CW-CP*2,"PERFORMANCE");
   cy+=LH+2;
   DrawL("C1B1",c1+4,cy,StringFormat("Win Rate: %.1f%%",d.wr),d.wr>=50?InpGreen:InpRed,9,false);
   cy+=LH;
   DrawB("C1BB",c1+4,cy,CW-CP*2-8,d.wr/100.0,d.wr>=50?InpGreen:InpRed);
   cy+=BH;
   DrawL("C1B2",c1+4,cy,StringFormat("PF: %.2f | Sharpe: %.2f | Kelly: %.1f%%",d.pf,d.sh,d.kl*100),InpText,9,false);
   cy+=LH;
   DrawL("C1B3",c1+4,cy,StringFormat("Trades: %d | Open: %d/%d | Daily: %d/%d",d.tt,d.ot,d.mt,d.dt,d.mdt),InpText,9,false);
   cy+=LH;
   DrawL("C1B4",c1+4,cy,StringFormat("Exp: $%.2f | Confidence: %.0f%%",d.exp,d.conf*100),InpText,9,false);
   cy+=LH+CGP;

   // Card: Strategy
   DrawC("C1C",c1,cy,CW-CP*2,"STRATEGY");
   cy+=LH+2;
   DrawL("C1C1",c1+4,cy,StringFormat("Method: %s",d.vm),InpYellow,9,true);
   cy+=LH;
   DrawL("C1C2",c1+4,cy,StringFormat("SL: %.1fx | TP: %.1fx | Risk: %.1f%%",d.cv,d.ct,d.cr),InpText,9,false);
   cy+=LH;
   DrawL("C1C3",c1+4,cy,StringFormat("Analysis: %d | Skips: %d",d.ac,d.sc),InpDim,9,false);
   cy+=LH+CGP;

   // Card: Technical Indicators
   DrawC("C1D",c1,cy,CW-CP*2,"INDICATORS");
   cy+=LH+2;
   DrawL("C1D1",c1+4,cy,StringFormat("RSI: %.1f | MACD: %s",d.rsi,d.mc),InpText,9,false);
   cy+=LH;
   DrawL("C1D2",c1+4,cy,StringFormat("Stoch K: %.1f | D: %.1f",d.sk,d.sd),InpText,9,false);
   cy+=LH;
   DrawL("C1D3",c1+4,cy,StringFormat("EMA20: %.5f | EMA50: %.5f",d.e20,d.e50),InpText,9,false);
   cy+=LH;
   DrawL("C1D4",c1+4,cy,StringFormat("EMA200: %.5f | ATR: %.5f",d.e200,d.atr2),InpText,9,false);
   cy+=LH;
   DrawL("C1D5",c1+4,cy,StringFormat("BB Upper: %.5f | Lower: %.5f",d.bu,d.bl),InpText,9,false);

   //=== COL 2: BRAIN + PROCESS ===
   int c2=PX+CW+CG+CP; cy=hy;

   // Card: Brain Status
   DrawC("C2A",c2,cy,CW-CP*2,"BRAIN STATUS");
   cy+=LH+2;
   DrawL("C2A1",c2+4,cy,StringFormat("Regime: %s | Session: %s",d.rg,d.se),InpText,9,false);
   cy+=LH;
   color cc=d.co=="BUY"?InpGreen:d.co=="SELL"?InpRed:InpYellow;
   DrawL("C2A2",c2+4,cy,StringFormat("Consensus: %s | Conf: %.0f%%",d.co,d.conf*100),cc,9,true);
   cy+=LH;
   DrawL("C2A3",c2+4,cy,StringFormat("Direction: %s | Circuit: %s",d.ld,d.cb),d.cb=="CLOSED"?InpGreen:InpRed,9,false);
   cy+=LH+CGP;

   // Card: Process Status
   DrawC("C2B",c2,cy,CW-CP*2,"PROCESS STATUS");
   cy+=LH+2;
   DrawL("C2B1",c2+4,cy,StringFormat("Threads: %d | Pool: %d | Symbols: %d",d.at,d.pw,d.sa),InpText,9,false);
   cy+=LH;
   DrawL("C2B2",c2+4,cy,StringFormat("Action: %s | Last: %s",d.ca,d.lt),InpYellow,9,false);
   cy+=LH;
   DrawL("C2B3",c2+4,cy,"Scan",InpText,8,false);
   DrawB("C2B3b",c2+35,cy,CW-CP*2-80,d.sp/100.0,InpBarFill);
   cy+=LH;
   DrawL("C2B4",c2+4,cy,"Analysis",InpText,8,false);
   DrawB("C2B4b",c2+35,cy,CW-CP*2-80,d.ap/100.0,C'0,200,100');
   cy+=LH;
   DrawL("C2B5",c2+4,cy,"Trade",InpText,8,false);
   DrawB("C2B5b",c2+35,cy,CW-CP*2-80,d.tp/100.0,C'255,160,0');
   cy+=LH+CGP;

   // Card: System
   DrawC("C2C",c2,cy,CW-CP*2,"SYSTEM");
   cy+=LH+2;
   DrawL("C2C1",c2+4,cy,"CPU",InpText,8,false);
   DrawB("C2C1b",c2+30,cy,CW-CP*2-70,d.cpu/100.0,d.cpu<60?InpGreen:d.cpu<85?InpYellow:InpRed);
   cy+=LH;
   DrawL("C2C2",c2+4,cy,"MEM",InpText,8,false);
   DrawB("C2C2b",c2+30,cy,CW-CP*2-70,d.mem/100.0,d.mem<60?InpGreen:d.mem<85?InpYellow:InpRed);
   cy+=LH;
   DrawL("C2C3",c2+4,cy,StringFormat("CPU: %d cores | MEM: %.1f/%.1fGB",d.cc,d.mu,d.mt2),InpDim,8,false);
   cy+=LH;
   DrawL("C2C4",c2+4,cy,StringFormat("Disk: %.1fGB free | Errors: %d",d.df,d.ec),InpDim,8,false);
   cy+=LH+CGP;

   // Card: Account Info
   DrawC("C2D",c2,cy,CW-CP*2,"ACCOUNT INFO");
   cy+=LH+2;
   DrawL("C2D1",c2+4,cy,StringFormat("Server: %s | Login: %d",d.sv,d.lg),InpText,9,false);
   cy+=LH;
   DrawL("C2D2",c2+4,cy,StringFormat("Company: %s",d.an),InpDim,8,false);

   //=== COL 3: MARKET + TRENDS + MACRO ===
   int c3=PX+2*CW+2*CG+CP; cy=hy;

   // Card: Symbol
   DrawC("C3A",c3,cy,CW-CP*2,"SYMBOL: "+d.cs2);
   cy+=LH+2;
   DrawL("C3A1",c3+4,cy,StringFormat("Bid: %.5f | Ask: %.5f | Spread: %d",d.cb2,d.ca2,d.cs3),InpText,9,false);
   cy+=LH;
   DrawL("C3A2",c3+4,cy,StringFormat("Point: %.5f | Digits: %d",d.cp2,d.cd),InpText,9,false);
   cy+=LH+CGP;

   // Card: MTF Trends + Timers
   DrawC("C3B",c3,cy,CW-CP*2,"MTF TRENDS & CANDLE TIMERS");
   cy+=LH+2;
   string tfn[]; ArrayResize(tfn,7);
   tfn[0]="M1";tfn[1]="M5";tfn[2]="M15";tfn[3]="M30";
   tfn[4]="H1";tfn[5]="H4";tfn[6]="D1";
   for(int i=0;i<7;i++)
   {
      color tc=InpDim;
      if(StringFind(d.tmr[i],"N/A")<0)
      {
         DrawL("C3B"+IntegerToString(i),c3+4,cy,StringFormat("%s: --- | Timer: %s",tfn[i],d.tmr[i]),InpText,9,false);
         // Timer bar
         DrawB("C3BT"+IntegerToString(i),c3+CW-CP*2-55,cy,50,d.tmr_p[i]/100.0,InpBarFill);
      }
      else
         DrawL("C3B"+IntegerToString(i),c3+4,cy,StringFormat("%s: --- | Timer: N/A",tfn[i]),InpDim,9,false);
      cy+=LH;
   }
   cy+=CGP;

   // Card: Macro/Sentiment
   DrawC("C3C",c3,cy,CW-CP*2,"MACRO & SENTIMENT");
   cy+=LH+2;
   DrawL("C3C1",c3+4,cy,StringFormat("Event: %s | Impact: %s",d.ne,d.ei),InpText,9,false);
   cy+=LH;
   DrawL("C3C2",c3+4,cy,StringFormat("Sentiment: Long %.0f%% | Short %.0f%%",d.sl,d.ss),InpText,9,false);
   cy+=LH+CGP;

   // Card: Positions Summary
   DrawC("C3D",c3,cy,CW-CP*2,"POSITIONS SUMMARY");
   cy+=LH+2;
   DrawL("C3D1",c3+4,cy,StringFormat("Open: %d | Volume: %.2f",d.ot,d.tov),InpText,9,false);
   cy+=LH;
   DrawL("C3D2",c3+4,cy,StringFormat("Total PnL: $%.2f",d.top),d.top>=0?InpGreen:InpRed,9,false);
}

//+------------------------------------------------------------------+
void DrawC(string id,int x,int y,int w,string t)
{
   string n="S_BG_"+id;
   ObjectCreate(0,n,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,n,OBJPROP_XSIZE,w);
   ObjectSetInteger(0,n,OBJPROP_YSIZE,LH*8+CP*2);
   ObjectSetInteger(0,n,OBJPROP_BGCOLOR,InpColBg);
   ObjectSetInteger(0,n,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,n,OBJPROP_COLOR,InpColBr);
   ObjectSetInteger(0,n,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   DrawL("CT_"+id,x+4,y+2,t,InpHdr,9,true);
}

void DrawL(string id,int x,int y,string t,color c,int s,bool b)
{
   string n="S_"+id;
   ObjectCreate(0,n,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,n,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetString(0,n,OBJPROP_TEXT,t);
   ObjectSetString(0,n,OBJPROP_FONT,b?"Consolas Bold":"Consolas");
   ObjectSetInteger(0,n,OBJPROP_FONTSIZE,s);
   ObjectSetInteger(0,n,OBJPROP_COLOR,c);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
}

void DrawB(string id,int x,int y,int w,double p,color fc)
{
   p=MathMax(0,MathMin(1,p));
   string bg="S_BAR_"+id; string fl="S_BARF_"+id;
   ObjectCreate(0,bg,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,bg,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,bg,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,bg,OBJPROP_XSIZE,w);
   ObjectSetInteger(0,bg,OBJPROP_YSIZE,BH);
   ObjectSetInteger(0,bg,OBJPROP_BGCOLOR,InpBarBg);
   ObjectSetInteger(0,bg,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,bg,OBJPROP_COLOR,InpBarBg);
   ObjectSetInteger(0,bg,OBJPROP_SELECTABLE,false);
   int fw=(int)(w*p);
   ObjectCreate(0,fl,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,fl,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,fl,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,fl,OBJPROP_XSIZE,MathMax(fw,1));
   ObjectSetInteger(0,fl,OBJPROP_YSIZE,BH);
   ObjectSetInteger(0,fl,OBJPROP_BGCOLOR,fc);
   ObjectSetInteger(0,fl,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,fl,OBJPROP_COLOR,fc);
   ObjectSetInteger(0,fl,OBJPROP_SELECTABLE,false);
}

void CreatePanel(int tw)
{
   string n="S_BG";
   ObjectCreate(0,n,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,PX);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,PY);
   ObjectSetInteger(0,n,OBJPROP_XSIZE,tw+10);
   ObjectSetInteger(0,n,OBJPROP_YSIZE,650);
   ObjectSetInteger(0,n,OBJPROP_BGCOLOR,InpBg);
   ObjectSetInteger(0,n,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,n,OBJPROP_COLOR,C'30,58,95');
   ObjectSetInteger(0,n,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
}
//+------------------------------------------------------------------+
