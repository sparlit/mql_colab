//+------------------------------------------------------------------+
//|                                      ScalperPro_Kanban.mq5       |
//|                          Scalper Pro — Live Kanban Dashboard      |
//+------------------------------------------------------------------+
#property copyright "Scalper Pro"
#property version   "26.00"
#property description "Live Kanban-Style Trading Dashboard"
#property indicator_chart_window

input group "--- UI Theme ---"
input color InpBgColor     = C'22,26,30';
input color InpCardColor   = C'29,35,41';
input color InpTextColor   = C'200,205,210';
input color InpAccentGreen = C'40,167,69';
input color InpAccentRed   = C'220,53,69';
input color InpAccentYellow= C'255,193,7';
input color InpAccentBlue  = C'13,110,253';
input int   InpFontSize    = 10;
input string InpDataPath   = "brain_data\\";

int totalColumns = 5;
int colWidth = 220;
int colGap = 10;
int panelTop = 40;
int cardHeight = 320;
string brainFile = "";

//+------------------------------------------------------------------+
string ReadFile(string f){int h=FileOpen(f,FILE_READ|FILE_TXT|FILE_COMMON);if(h==INVALID_HANDLE)h=FileOpen(f,FILE_READ|FILE_TXT);if(h==INVALID_HANDLE)return"";string c="";while(!FileIsEnding(h))c+=FileReadString(h);FileClose(h);return c;}
double JD(string j,string k){string s="\""+k+"\":";int p=StringFind(j,s);if(p<0)return 0;string sub=StringSubstr(j,p+StringLen(s));StringTrimLeft(sub);if(StringLen(sub)==0)return 0;ushort ch=StringGetCharacter(sub,0);if(ch=='"'||ch=='t'||ch=='n')return 0;string n="";for(int i=0;i<MathMin(StringLen(sub),30);i++){ch=StringGetCharacter(sub,i);if((ch>='0'&&ch<='9')||ch=='.'||ch=='-'||ch=='+')n+=ShortToString(ch);else if(StringLen(n)>0)break;}return StringLen(n)>0?StringToDouble(n):0;}
string JS(string j,string k){string s="\""+k+"\":\"";int p=StringFind(j,s);if(p<0)return"";int st=p+StringLen(s);int en=StringFind(j,"\"",st);if(en<0)return"";return StringSubstr(j,st,en-st);}

//+------------------------------------------------------------------+
int OnInit(){
   brainFile=InpDataPath+"brain_status.json";
   ObjectsDeleteAll(0,"KB_");
   CreateBackground();
   
   string cols[5]={"1. ACCOUNT & RISK","2. MARKET WATCH","3. TECHNICAL TRENDS","4. ACTIVE TRADES","5. BRAIN STATUS"};
   for(int i=0;i<totalColumns;i++){
      int xPos=20+i*(colWidth+colGap);
      CreateColumnContainer(cols[i],"KB_COL_"+IntegerToString(i),xPos,panelTop);
   }
   
   RefreshData();
   ChartRedraw(0);
   Print("=== SCALPER PRO KANBAN v26 ===");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason){ObjectsDeleteAll(0,"KB_");ChartRedraw(0);}
void OnTick(){RefreshData();}
void OnTimer(){RefreshData();}

//+------------------------------------------------------------------+
void CreateBackground(){
   string name="KB_MAIN_BG";
   ObjectCreate(0,name,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,0);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,0);
   ObjectSetInteger(0,name,OBJPROP_XSIZE,2000);
   ObjectSetInteger(0,name,OBJPROP_YSIZE,1080);
   ObjectSetInteger(0,name,OBJPROP_BGCOLOR,InpBgColor);
   ObjectSetInteger(0,name,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,name,OBJPROP_BACK,true);
}

//+------------------------------------------------------------------+
void CreateColumnContainer(string headerText,string objPrefix,int x,int y){
   string bgName=objPrefix+"_BG";
   ObjectCreate(0,bgName,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,bgName,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,bgName,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,bgName,OBJPROP_XSIZE,colWidth);
   ObjectSetInteger(0,bgName,OBJPROP_YSIZE,cardHeight);
   ObjectSetInteger(0,bgName,OBJPROP_BGCOLOR,InpCardColor);
   ObjectSetInteger(0,bgName,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   
   string textName=objPrefix+"_TXT";
   ObjectCreate(0,textName,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,textName,OBJPROP_XDISTANCE,x+10);
   ObjectSetInteger(0,textName,OBJPROP_YDISTANCE,y+10);
   ObjectSetString(0,textName,OBJPROP_TEXT,headerText);
   ObjectSetString(0,textName,OBJPROP_FONT,"Segoe UI Semibold");
   ObjectSetInteger(0,textName,OBJPROP_FONTSIZE,11);
   ObjectSetInteger(0,textName,OBJPROP_COLOR,InpAccentBlue);
}

//+------------------------------------------------------------------+
void RefreshData(){
   // Live MT5 data
   string sym=Symbol();
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   int spread=(int)SymbolInfoInteger(sym,SYMBOL_SPREAD);
   int digits=(int)SymbolInfoInteger(sym,SYMBOL_DIGITS);
   
   // Account
   double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double profit=AccountInfoDouble(ACCOUNT_PROFIT);
   double marginLvl=AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   double freeMargin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   
   // Indicators
   double rsi=0,macd_v=0,macd_s=0,stoch_k=0,stoch_d=0;
   double ema20=0,ema50=0,ema200=0,atr=0,bb_u=0,bb_l=0;
   int h;
   h=iRSI(sym,PERIOD_CURRENT,14,PRICE_CLOSE);if(h!=INVALID_HANDLE){double b[];ArraySetAsSeries(b,true);if(CopyBuffer(h,0,0,1,b)>0)rsi=b[0];IndicatorRelease(h);}
   h=iMACD(sym,PERIOD_CURRENT,12,26,9,PRICE_CLOSE);if(h!=INVALID_HANDLE){double m[],s[];ArraySetAsSeries(m,true);ArraySetAsSeries(s,true);if(CopyBuffer(h,0,0,1,m)>0&&CopyBuffer(h,1,0,1,s)>0){macd_v=m[0];macd_s=s[0];}IndicatorRelease(h);}
   h=iStochastic(sym,PERIOD_CURRENT,14,3,3,MODE_SMA,0);if(h!=INVALID_HANDLE){double k[],d[];ArraySetAsSeries(k,true);ArraySetAsSeries(d,true);if(CopyBuffer(h,0,0,1,k)>0&&CopyBuffer(h,1,0,1,d)>0){stoch_k=k[0];stoch_d=d[0];}IndicatorRelease(h);}
   h=iMA(sym,PERIOD_CURRENT,20,0,MODE_EMA,PRICE_CLOSE);if(h!=INVALID_HANDLE){double b[];ArraySetAsSeries(b,true);if(CopyBuffer(h,0,0,1,b)>0)ema20=b[0];IndicatorRelease(h);}
   h=iMA(sym,PERIOD_CURRENT,50,0,MODE_EMA,PRICE_CLOSE);if(h!=INVALID_HANDLE){double b[];ArraySetAsSeries(b,true);if(CopyBuffer(h,0,0,1,b)>0)ema50=b[0];IndicatorRelease(h);}
   h=iMA(sym,PERIOD_CURRENT,200,0,MODE_EMA,PRICE_CLOSE);if(h!=INVALID_HANDLE){double b[];ArraySetAsSeries(b,true);if(CopyBuffer(h,0,0,1,b)>0)ema200=b[0];IndicatorRelease(h);}
   h=iATR(sym,PERIOD_CURRENT,14);if(h!=INVALID_HANDLE){double b[];ArraySetAsSeries(b,true);if(CopyBuffer(h,0,0,1,b)>0)atr=b[0];IndicatorRelease(h);}
   h=iBands(sym,PERIOD_CURRENT,20,0,2.0,PRICE_CLOSE);if(h!=INVALID_HANDLE){double u[],l[];ArraySetAsSeries(u,true);ArraySetAsSeries(l,true);if(CopyBuffer(h,1,0,1,u)>0&&CopyBuffer(h,2,0,1,l)>0){bb_u=u[0];bb_l=l[0];}IndicatorRelease(h);}
   
   string trend="NEUTRAL";if(bid>ema20&&ema20>ema50)trend="BUY";else if(bid<ema20&&ema20<ema50)trend="SELL";
   string macd_cross=(macd_v>macd_s)?"BULL":"BEAR";
   
   // Brain data
   string c=ReadFile(brainFile);if(StringLen(c)==0)c=ReadFile("brain_data\\brain_status.json");
   string regime="?",session="?",consensus="?",circuit="?",method="?",next_sess="?",next_in="?";
   string sess_utc="?",sess_local="?",sess_st="?";
   double bal=0,eq=0,dp=0,wr=0,pf=0,conf=0,hs=0,cpu=0,mem=0;
   int ot=0,dt=0,mdt=0,tt=0;
   if(StringLen(c)>0){bal=JD(c,"balance");eq=JD(c,"equity");dp=JD(c,"daily_pnl");wr=JD(c,"win_rate");pf=JD(c,"profit_factor");conf=JD(c,"confidence");hs=JD(c,"health_score");cpu=JD(c,"cpu_overall");mem=JD(c,"mem_percent");ot=(int)JD(c,"open_trades");dt=(int)JD(c,"daily_trades");mdt=(int)JD(c,"max_daily_trades");tt=(int)JD(c,"total_trades");regime=JS(c,"regime");session=JS(c,"session");consensus=JS(c,"consensus");circuit=JS(c,"circuit_breaker");method=JS(c,"v11_method");next_sess=JS(c,"next_session");next_in=JS(c,"next_session_in");sess_utc=JS(c,"session_utc");sess_local=JS(c,"session_local");sess_st=JS(c,"session_status");}
   
   datetime bar_time=iTime(sym,PERIOD_CURRENT,0);int period_sec=PeriodSeconds(PERIOD_CURRENT);int remaining=period_sec-(int)(TimeCurrent()-bar_time);
   string countdown=StringFormat("%02d:%02d",remaining/60,remaining%60);
   double dd_pct=(eq<balance)?((balance-equity)/balance*100):0;
   
    int sx=30;int sy=panelTop+45;int ls=18;
    
    // ═══ COLUMN 1: ACCOUNT & RISK ═══
    UpdateLabel("KB_C1_1","Balance:  $"+DoubleToString(balance,2),sx,sy,InpTextColor);
    UpdateLabel("KB_C1_2","Equity:   $"+DoubleToString(equity,2),sx,sy+ls,(equity>=balance)?InpAccentGreen:InpAccentRed);
    UpdateLabel("KB_C1_3","P/L:      $"+DoubleToString(profit,2),sx,sy+ls*2,(profit>=0)?InpAccentGreen:InpAccentRed);
    UpdateLabel("KB_C1_4","DD:       "+DoubleToString(dd_pct,1)+"%",sx,sy+ls*3,(dd_pct>5)?InpAccentRed:InpTextColor);
    UpdateLabel("KB_C1_5","Open:     "+IntegerToString(ot)+" | "+IntegerToString(dt)+"/"+IntegerToString(mdt),sx,sy+ls*4,InpTextColor);
    UpdateLabel("KB_C1_6","WinRate:  "+DoubleToString(wr,1)+"% | PF: "+DoubleToString(pf,2),sx,sy+ls*5,InpTextColor);
    UpdateLabel("KB_C1_7","Free:     $"+DoubleToString(freeMargin,2)+" | ML: "+DoubleToString(marginLvl,0)+"%",sx,sy+ls*6,InpAccentGreen);
    UpdateLabel("KB_C1_8","Method:   "+method,sx,sy+ls*7,InpAccentYellow);
    UpdateLabel("KB_C1_9","Session:  "+session+" | "+sess_st,sx,sy+ls*8,InpTextColor);
    UpdateLabel("KB_C1_10","Circuit:  "+circuit,sx,sy+ls*9,(circuit=="OPEN")?InpAccentRed:InpAccentGreen);
   
   int c2x=20+(colWidth+colGap);
   
    // ═══ COLUMN 2: MARKET WATCH ═══
    UpdateLabel("KB_C2_1","Bid:     "+DoubleToString(bid,digits),c2x,sy,InpTextColor);
    UpdateLabel("KB_C2_2","Ask:     "+DoubleToString(ask,digits),c2x,sy+ls,InpTextColor);
    UpdateLabel("KB_C2_3","Spread:  "+IntegerToString(spread)+" pts",c2x,sy+ls*2,InpTextColor);
    UpdateLabel("KB_C2_4","Trend:   "+trend,c2x,sy+ls*3,(trend=="BUY")?InpAccentGreen:(trend=="SELL")?InpAccentRed:InpAccentYellow);
    UpdateLabel("KB_C2_5","MACD:    "+macd_cross,c2x,sy+ls*4,(macd_cross=="BULL")?InpAccentGreen:InpAccentRed);
    UpdateLabel("KB_C2_6","Next:    "+next_sess+" in "+next_in,c2x,sy+ls*5,InpAccentYellow);
    UpdateLabel("KB_C2_7","Session: "+session+" | "+sess_st,c2x,sy+ls*6,InpTextColor);
    UpdateLabel("KB_C2_8","Countdown:"+countdown,c2x,sy+ls*7,InpAccentGreen);
    UpdateLabel("KB_C2_9","Clock:   "+TimeToString(TimeCurrent(),TIME_SECONDS),c2x,sy+ls*8,InpTextColor);
    UpdateLabel("KB_C2_10","Trend:   "+trend,c2x,sy+ls*9,(trend=="BUY")?InpAccentGreen:(trend=="SELL")?InpAccentRed:InpAccentYellow);
    
    int c3x=20+(colWidth+colGap)*2;
    
    // ═══ COLUMN 3: TECHNICAL TRENDS ═══
    UpdateLabel("KB_C3_1","RSI:     "+DoubleToString(rsi,1),c3x,sy,(rsi<30)?InpAccentGreen:(rsi>70)?InpAccentRed:InpTextColor);
    UpdateLabel("KB_C3_2","MACD:    "+DoubleToString(macd_v,5),c3x,sy+ls,(macd_v>macd_s)?InpAccentGreen:InpAccentRed);
    UpdateLabel("KB_C3_3","Signal:  "+DoubleToString(macd_s,5),c3x,sy+ls*2,InpTextColor);
    UpdateLabel("KB_C3_4","Stoch:   "+DoubleToString(stoch_k,1)+"/"+DoubleToString(stoch_d,1),c3x,sy+ls*3,InpTextColor);
    UpdateLabel("KB_C3_5","EMA20:   "+DoubleToString(ema20,digits),c3x,sy+ls*4,InpTextColor);
    UpdateLabel("KB_C3_6","EMA50:   "+DoubleToString(ema50,digits),c3x,sy+ls*5,InpTextColor);
    UpdateLabel("KB_C3_7","EMA200:  "+DoubleToString(ema200,digits),c3x,sy+ls*6,InpTextColor);
    UpdateLabel("KB_C3_8","ATR:     "+DoubleToString(atr,digits),c3x,sy+ls*7,InpTextColor);
    UpdateLabel("KB_C3_9","BB:      "+DoubleToString(bb_u,digits)+"/"+DoubleToString(bb_l,digits),c3x,sy+ls*8,InpTextColor);
    UpdateLabel("KB_C3_10","Cross:   "+macd_cross,c3x,sy+ls*9,(macd_cross=="BULL")?InpAccentGreen:InpAccentRed);
   
   int c4x=20+(colWidth+colGap)*3;
   
   // ═══ COLUMN 4: ACTIVE TRADES ═══
   long posTotal=PositionsTotal();
   int posCount=(int)MathMin(posTotal,8);
   if(posCount==0){
      UpdateLabel("KB_C4_1","No open positions",c4x,sy,InpAccentYellow);
   }else{
      UpdateLabel("KB_C4_1","Symbol   Type   Vol     Profit",c4x,sy,InpAccentBlue);
      for(int i=0;i<posCount;i++){
         ulong ticket=PositionGetTicket(i);
         if(ticket>0){
            string posSym=PositionGetString(POSITION_SYMBOL);
            double posProfit=PositionGetDouble(POSITION_PROFIT);
            double posVol=PositionGetDouble(POSITION_VOLUME);
            long posType=PositionGetInteger(POSITION_TYPE);
            string typeStr=(posType==POSITION_TYPE_BUY)?"BUY":"SELL";
            color profitClr=(posProfit>=0)?InpAccentGreen:InpAccentRed;
            UpdateLabel("KB_C4_"+IntegerToString(i+2),posSym+" "+typeStr+" "+DoubleToString(posVol,2)+" "+DoubleToString(posProfit,2),c4x,sy+ls*(i+1),profitClr);
         }
      }
   }
   
   int c5x=20+(colWidth+colGap)*4;
   
   // ═══ COLUMN 5: BRAIN STATUS ═══
   UpdateLabel("KB_C5_1","Method:   "+method,c5x,sy,InpAccentYellow);
   UpdateLabel("KB_C5_2","Regime:   "+regime,c5x,sy+ls,InpTextColor);
   UpdateLabel("KB_C5_3","Consensus:"+consensus,c5x,sy+ls*2,InpTextColor);
   UpdateLabel("KB_C5_4","Circuit:  "+circuit,c5x,sy+ls*3,(circuit=="OPEN")?InpAccentRed:InpAccentGreen);
   UpdateLabel("KB_C5_5","Conf:     "+DoubleToString(conf,2),c5x,sy+ls*4,InpTextColor);
   UpdateLabel("KB_C5_6","Session:  "+session,c5x,sy+ls*5,InpTextColor);
   UpdateLabel("KB_C5_7","Next:     "+next_sess+" in "+next_in,c5x,sy+ls*6,InpAccentYellow);
   UpdateLabel("KB_C5_8","UTC:      "+sess_utc,c5x,sy+ls*7,InpTextColor);
   UpdateLabel("KB_C5_9","Local:    "+sess_local,c5x,sy+ls*8,InpTextColor);
   UpdateLabel("KB_C5_10","Status:   "+sess_st,c5x,sy+ls*9,InpTextColor);
   
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
void UpdateLabel(string name,string text,int x,int y,color textCol){
   if(ObjectFind(0,name)<0) ObjectCreate(0,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,y);
   ObjectSetString(0,name,OBJPROP_TEXT,text);
   ObjectSetString(0,name,OBJPROP_FONT,"Consolas");
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,InpFontSize);
   ObjectSetInteger(0,name,OBJPROP_COLOR,textCol);
}
//+------------------------------------------------------------------+
