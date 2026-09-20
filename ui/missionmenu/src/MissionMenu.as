package
{
   import Components.BSButton;
   import Shared.AS3.BS3DSceneRectManager;
   import Shared.AS3.BSAnimating3DSceneRect;
   import Shared.AS3.BSScrollingConfigParams;
   import Shared.AS3.BSTabbedSelection;
   import Shared.AS3.BSTabbedSelectionEvent;
   import Shared.AS3.Data.BSUIDataManager;
   import Shared.AS3.Data.FromClientDataEvent;
   import Shared.AS3.Events.CustomEvent;
   import Shared.AS3.Events.ScrollingEvent;
   import Shared.AS3.IMenu;
   import Shared.FactionUtils;
   import Shared.Components.ButtonControls.ButtonBar.ButtonBar;
   import Shared.Components.ButtonControls.ButtonData.ButtonBaseData;
   import Shared.Components.ButtonControls.ButtonData.ButtonData;
   import Shared.Components.ButtonControls.ButtonData.ReleaseHoldComboButtonData;
   import Shared.Components.ButtonControls.ButtonData.UserEventData;
   import Shared.Components.ButtonControls.ButtonFactory.ButtonFactory;
   import Shared.Components.ButtonControls.Buttons.ButtonBase;
   import Shared.Components.ButtonControls.Buttons.IButton;
   import Shared.Components.ButtonControls.Utils.ButtonKeyHelper;
   import Shared.GlobalFunc;
   import Shared.PlatformUtils;
   import Shared.QuestUtils;
   import flash.display.MovieClip;
   import flash.events.Event;
   import flash.events.TimerEvent;
   import flash.utils.Timer;
   
   [Embed(source="/_assets/assets.swf", symbol="symbol94")]
   public class MissionMenu extends IMenu
   {
      
      public static const LERP_DELAY_TIME:Number = 0.2;
      
      public static const MISSION_ANIMATION_DELAY_TIME:Number = 0.25;
      
      public static const MISSION_FADE_IN_TIME:Number = 0.4;
      
      public static const OBJECTIVE_ANIMATION_DELAY_TIME:Number = 0.1;
      
      public static const OBJECTIVE_FADE_IN_TIME:Number = 0.4;
      
      public static const OBJECTIVE_LIST_OFFSET:Number = 300;
      
      public static const KEYBOARD_TAB_BUTTON_OFFSET:Number = 1.25;
      
      private static const SHOW_ITEM_LOCATION_EVENT:String = "MissionMenu_ShowItemLocation";
      
      private static const MissionMenu_PlotToLocation:String = "MissionMenu_PlotToLocation";
      
      private static const MissionMenu_ToggleTrackingQuest:String = "MissionMenu_ToggleTrackingQuest";
      
      private static const MissionMenu_RejectQuest:String = "MissionMenu_RejectQuest";
      
      private static const MissionMenu_SaveOpenedId:String = "MissionMenu_SaveOpenedId";
      
      private static const MissionMenu_SaveCategoryIndex:String = "MissionMenu_SaveCategoryIndex";
      
      private static const MissionMenu_ClearState:String = "MissionMenu_ClearState";
      
      public static const MissionMenu_OnExitMissionMenu:String = "MissionMenu_OnExitMissionMenu";
      
      protected static const TIMELINE_CLOSE_EVENT:String = "TimelineCloseEvent";
      
      public static const MISSION_SELECTION_CHANGE_SOUND:String = "UIMenuMissionsMenuSelectionChange";
      
      public static const MISSION_CATEGORY_CHANGE_SOUND:String = "UIMenuMissionsMenuCategoryChange";
      
      public static const MISSION_SUBTASK_TOGGLE_SOUND:String = "UIMenuMissionsMenuSubtasksToggle";
      
      public static const MISSION_TRACKING_TOGGLE_ON_SOUND:String = "UIMenuMissionsMenuTrackingToggleOn";
      
      public static const MISSION_TRACKING_TOGGLE_OFF_SOUND:String = "UIMenuMissionsMenuTrackingToggleOff";
      
      public static const MISSION_SHOW_ON_MAP_SOUND:String = "UIMenuMissionsMenuShowOnMap";
      
      // ===================================================================
      //  SAQ（Show Available Quests）：新增「可接任务」tab
      //
      //  数据来源有两层，C++ 推送优先，没有推送时用内嵌的回退表：
      //    ① C++ 插件 Invoke("SetAvailableQuests", <载荷>)  —— 载荷协议见下
      //    ② SAQ_EMBEDDED_CHUNKS（构建时由 tools/esm/gen_quest_table.py 生成，
      //       tools/build-saq.ps1 替换掉下面的 /*__SAQ_EMBEDDED__*/ 标记）
      //
      //  载荷协议（一行一条，Tab 分隔，名字放最后）：
      //      SAQ1
      //      T\t<中文标题>\t<英文标题>
      //      Q\t<FormID>\t<type>\t<中文名>\t<英文名>
      //  兼容旧版 3 字段 Q 行（只有中文名 = 中英同名）。
      //
      //  语言判定放在 AS3 侧：**引擎推给 UI 的 QuestData 里就是本地化的任务名**，
      //  比 C++ 去读 INI（本机实测读不到 sLanguage）可靠得多。
      // ===================================================================
      
      private static const SAQ_TITLE_ZH:String = "可接任务";
      
      private static const SAQ_TITLE_EN:String = "Available";
      
      private static const SAQ_EMBEDDED_CHUNKS:Array = [/*__SAQ_EMBEDDED__*/];
      
      public var UniversalBackButton_mc:BSButton;
      
      public var ButtonBar_mc:ButtonBar;
      
      public var MissionsList_mc:MissionsList;
      
      public var MissionInfo_mc:MissionInfo;
      
      public var TabbedFilterSelection_mc:MissionTabbedSelection;
      
      public var Vignette_mc:MovieClip;
      
      public var PreviewSceneRect_mc:BSAnimating3DSceneRect;
      
      private var ButtonBarRefreshTimer:Timer = null;
      
      private var PreviousMissionIndex:int = -1;
      
      private var bClosing:Boolean = false;
      
      private var QuestData:Array = null;
      
      private var AvailableQuests:Array = null;
      
      private var RawAvailableQuests:Array = null;
      
      private var SaqSourcePayload:String = null;
      
      private var SaqSourceIsCpp:Boolean = false;
      
      private var SaqRawQuests:Array = null;
      
      private var SaqTitleZh:String = null;
      
      private var SaqTitleEn:String = null;
      
      private var SaqLangKnown:Boolean = false;
      
      private var SaqLangZh:Boolean = false;
      
      private var SaqTabProbe:String = "-";

      private var SaqOurTabProbe:String = "-";

      private var SaqOurTabMaxList:int = -1;

      // ★ 第 19 轮：最近一次 FilterKnownQuests 过滤掉的「玩家已有」uID 名单（日志诊断用）。
      private var SaqDropList:String = "-";

      private var SaqDropCount:int = 0;

      // ---- 引导（第 10 轮）------------------------------------------------
      // 玩家在「可接任务」tab 里选中一条、按 Enter 或 SET COURSE（键盘 R / 手柄 X）时：
      //   SaqGuideSeq++ / SaqGuideQuest = 任务 FormID（0 = 取消）
      //   → C++ 侧（SAQ.cpp::PollGuideRequest）读到序号变化 → 把「引导目标引用」写进 ESM 的
      //     GLOB → Papyrus（SAQ_Main.psc）在那条代理任务上 ForceRefTo + 显示目标 + 设为追踪
      //   → 引擎画出任务标记（蓝点）与扫描仪路径线。
      // 为什么要绕这一圈：未接取的任务引擎根本不追踪，这是「借引擎的标记系统一用」。
      private var SaqGuideSeq:int = 0;

      private var SaqGuideQuest:Number = 0;

      // 最近一次引导动作（进报告，日志里能看出玩家点了什么）
      private var SaqGuideNote:String = "-";

      private var StoredLastOpenedIds:Array = null;
      
      private var StoredLastCategory:uint = 0;
      
      private var InitializedOpenedIds:Boolean = false;
      
      private var bReturningToGame:Boolean = false;
      
      private var FilterInfoA:Array;
      
      private var lastSelectedIndex:int = -1;
      
      private var bCollapsing:Boolean = false;
      
      private var bWithinMiscQuest:Boolean = false;
      
      private var miscQuestIndex:int = 0;
      
      private var scrollPositionAtTracking:int = -1;
      
      private var startingTabButtonYPosition:Number = 0;
      
      private var bWrappedAroundUp:Boolean = false;
      
      private var bSkipSelectionSounds:Boolean = false;
      
      private var KeyHelper:ButtonKeyHelper = null;
      
      private var bButtonBarInitialized:Boolean = false;
      
      private var canReject:Boolean = false;
      
      private var CanTrackOrUntrack:Boolean = false;
      
      private var ShowAllQTsBtnData:ButtonBaseData;
      
      private var ShowOnlyActiveQTsBtnData:ButtonBaseData;
      
      private var ToggleQTDisplayButton:IButton;
      
      private var ShowOnlyActiveQTs:Boolean = true;
      
      public function MissionMenu()
      {
         this.ShowAllQTsBtnData = new ButtonBaseData("$ToggleShowAllQTs",[new UserEventData("Select",this.ToggleQTDisplay)]);
         this.ShowOnlyActiveQTsBtnData = new ButtonBaseData("$ToggleShowOnlyActiveQTs",[new UserEventData("Select",this.ToggleQTDisplay)]);
         super();
         addFrameScript(8,this.frame9,16,this.frame17);
         this.PreviewSceneRect_mc.SetBackgroundColor(67504895);
         BS3DSceneRectManager.Register3DSceneRect(this.PreviewSceneRect_mc);
         gotoAndPlay("Open");
         addEventListener(TIMELINE_CLOSE_EVENT,this.OnTimelineCloseEvent);
         this.ButtonBar_mc.visible = false;
         this.PopulateTabs();
         this.MissionsList_mc.addEventListener(ScrollingEvent.SELECTION_CHANGE,this.onMissionSelectionChange);
         addEventListener(MissionsList.ITEM_ACTIVATED,this.onMissionListItemActivated);
         this.UniversalBackButton_mc.addEventListener(BSButton.BUTTON_CLICKED_EVENT,this.OnCancelEvent);
         var _loc1_:BSScrollingConfigParams = new BSScrollingConfigParams();
         _loc1_.VerticalSpacing = 3;
         _loc1_.EntryClassName = "MissionsListEntry";
         this.MissionsList_mc.Configure(_loc1_);
      }
      
      public function get currentFilterIndex() : int
      {
         return this.TabbedFilterSelection_mc.selectedIndex;
      }
      
      public function get currentFilterFlag() : int
      {
         return this.FilterInfoA[this.currentFilterIndex].flag;
      }
      
      private function get ShowOnMapButton() : IButton
      {
         return this.ButtonBar_mc.ShowOnMapButton_mc;
      }
      
      private function get PlotToLocationButton() : IButton
      {
         return this.ButtonBar_mc.PlotToLocationButton_mc;
      }
      
      private function get BackButton() : IButton
      {
         return this.ButtonBar_mc.BackButton_mc;
      }
      
      private function get RejectQuestButton() : IButton
      {
         return this.ButtonBar_mc.RejectButton_mc;
      }
      
      private function PopulateButtonBar() : void
      {
         var _loc1_:String = null;
         var _loc2_:String = null;
         if(!this.bButtonBarInitialized)
         {
            _loc1_ = this.KeyHelper.GetButtonNameForEvent("XButton","");
            if(_loc1_.length != 0)
            {
               this.bButtonBarInitialized = true;
               this.ButtonBar_mc.Initialize(ButtonBar.JUSTIFY_RIGHT);
               this.ToggleQTDisplayButton = ButtonFactory.AddToButtonBar("BasicButton",this.ShowOnlyActiveQTs ? this.ShowAllQTsBtnData : this.ShowOnlyActiveQTsBtnData,this.ButtonBar_mc);
               this.ButtonBar_mc.AddButtonWithData(this.ShowOnMapButton,new ButtonBaseData("$SHOWONMAP",[new UserEventData("YButton",this.OnShowOnMapEvent)],false,true));
               this.ButtonBar_mc.AddButtonWithData(this.PlotToLocationButton,new ButtonBaseData("$SET COURSE",[new UserEventData("XButton",this.OnPlotCourseEvent)],false,true));
               this.RejectQuestButton.Visible = this.canReject;
               this.ButtonBar_mc.AddButtonWithData(this.RejectQuestButton,new ButtonBaseData("$REJECT",[new UserEventData("R3",this.OnRejectQuest)],true,this.canReject));
               _loc2_ = "$EXIT HOLD";
               this.ButtonBar_mc.AddButtonWithData(this.BackButton,new ReleaseHoldComboButtonData("$BACK",_loc2_,[new UserEventData("Cancel",this.OnCancelEvent),new UserEventData("",this.onCloseSubMenuToGame)]));
               (this.ShowOnMapButton as ButtonBase).RefreshButtonData();
               (this.PlotToLocationButton as ButtonBase).RefreshButtonData();
               (this.RejectQuestButton as ButtonBase).RefreshButtonData();
               (this.BackButton as ButtonBase).RefreshButtonData();
               this.ButtonBar_mc.RefreshButtons();
               this.ButtonBar_mc.redrawDisplayObject();
               this.ButtonBarRefreshTimer = new Timer(60,1);
               this.ButtonBarRefreshTimer.addEventListener(TimerEvent.TIMER,this.handleButtonBarRefreshTimer);
               this.ButtonBarRefreshTimer.start();
               this.onMissionSelectionChange();
            }
         }
      }
      
      private function handleButtonBarRefreshTimer(param1:TimerEvent) : *
      {
         this.ButtonBar_mc.visible = true;
         this.ButtonBarRefreshTimer = null;
      }
      
      private function UpdateRejectData(param1:Boolean) : void
      {
         if(param1 != this.canReject)
         {
            this.canReject = param1;
            this.RejectQuestButton.Visible = param1;
            this.ButtonBar_mc.RefreshButtons();
         }
      }
      
      private function PopulateTabs() : void
      {
         this.FilterInfoA = new Array();
         // ★ 「全部」这一位的掩码从 0xFFFFFFFF 改成 0xFFFFFFBF
         //   即去掉 (1 << AVAILABLE_QUEST_TYPE)：未接任务只在我们的 tab 里出现，
         //   不污染原版「全部」列表（否则一进菜单就看到一堆没有目标的条目）。
         this.FilterInfoA.push({
            "text":"$ALL",
            "flag":4294967231
         });
         this.FilterInfoA.push({
            "text":"$Main",
            "flag":1 << QuestUtils.MAIN_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Faction",
            "flag":1 << QuestUtils.FACTION_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Misc",
            "flag":1 << QuestUtils.MISC_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$MISSION",
            "flag":1 << QuestUtils.MISSION_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Activity",
            "flag":1 << QuestUtils.ACTIVITY_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Completed",
            "flag":1 << QuestUtils.COMPLETED_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":this.SaqTabTitle(),
            "flag":1 << QuestUtils.AVAILABLE_QUEST_TYPE
         });
         this.TabbedFilterSelection_mc.SetTabsData(this.FilterInfoA);
         this.TabbedFilterSelection_mc.addEventListener(BSTabbedSelectionEvent.NAME,this.onFilterChanged);
         this.startingTabButtonYPosition = this.TabbedFilterSelection_mc.LeftButton.y;
      }
      
      private function SetAvailableTabText(param1:String) : void
      {
         if(param1 != null && param1.length > 0 && this.FilterInfoA != null && this.FilterInfoA.length > 0)
         {
            if(this.FilterInfoA[this.FilterInfoA.length - 1].text == param1)
            {
               return;
            }
            this.FilterInfoA[this.FilterInfoA.length - 1].text = param1;
            this.TabbedFilterSelection_mc.SetTabsData(this.FilterInfoA);
         }
      }
      
      private function BuildMergedList() : Array
      {
         var _loc1_:Array = this.QuestData == null ? new Array() : this.QuestData;
         if(this.AvailableQuests != null && this.AvailableQuests.length > 0)
         {
            _loc1_ = _loc1_.concat(this.AvailableQuests);
         }
         return _loc1_;
      }
      
      private function FilterKnownQuests(param1:Array) : Array
      {
         if(param1 == null)
         {
            return null;
         }
         var _loc2_:Object = {};
         if(this.QuestData != null)
         {
            var _loc3_:int = 0;
            while(_loc3_ < this.QuestData.length)
            {
               _loc2_[this.QuestData[_loc3_].uID] = true;
               _loc3_++;
            }
         }
         var _loc4_:Array = new Array();
         var _loc5_:int = 0;
         // ★ 第 19 轮：记录被过滤掉的 uID 名单（最多 12 条，进 SAQ_Report 的 drop=）。
         //   用途：C++ 的 `raw=` 与 `keep=` 差几条时，日志直接给出「是哪几条」，
         //   不用再人肉比对 qdata 名单（第 18 轮实测：raw=260 keep=257 少 3 条，无从确认）。
         var _loc6_:String = "";
         var _loc7_:int = 0;
         while(_loc5_ < param1.length)
         {
            if(!_loc2_[param1[_loc5_].uID])
            {
               _loc4_.push(param1[_loc5_]);
            }
            else if(_loc7_ < 12)
            {
               _loc7_++;
               _loc6_ += (_loc7_ > 1 ? "," : "") + param1[_loc5_].uID.toString(16);
            }
            _loc5_++;
         }
         this.SaqDropCount = _loc7_;
         this.SaqDropList = _loc7_ > 0 ? _loc6_ : "-";
         return _loc4_;
      }
      
      // ------------------------------------------------------------------
      //  SAQ 主体
      // ------------------------------------------------------------------

      // 判断一段文本「像不像中文」：1 = 中文，-1 = 明确不是（拉丁/假名/谚文），
      // 0 = 判不出来（纯符号/数字/空）。
      private static function SaqNameVerdict(param1:String) : int
      {
         if(param1 == null || param1.length == 0)
         {
            return 0;
         }
         var _loc2_:int = 0;
         while(_loc2_ < param1.length)
         {
            var _loc3_:int = param1.charCodeAt(_loc2_);
            if(_loc3_ >= 12352 && _loc3_ <= 12543)
            {
               return -1;
            }
            if(_loc3_ >= 44032 && _loc3_ <= 55215)
            {
               return -1;
            }
            if(_loc3_ >= 19968 && _loc3_ <= 40959)
            {
               return 1;
            }
            if(_loc3_ >= 32 && _loc3_ < 8704)
            {
               return -1;
            }
            _loc2_++;
         }
         return 0;
      }
      
      // 游戏是不是中文（判定依据：引擎推来的任务名本身就是本地化的）
      private function SaqUseChinese() : Boolean
      {
         if(this.SaqLangKnown)
         {
            return this.SaqLangZh;
         }
         if(this.QuestData != null)
         {
            var _loc1_:int = 0;
            while(_loc1_ < this.QuestData.length)
            {
               var _loc2_:Object = this.QuestData[_loc1_];
               var _loc3_:int = _loc2_ != null ? SaqNameVerdict(_loc2_.sName) : 0;
               if(_loc3_ != 0)
               {
                  this.SaqLangZh = _loc3_ > 0;
                  this.SaqLangKnown = true;
                  return this.SaqLangZh;
               }
               _loc1_++;
            }
         }
         return this.SaqLangZh;
      }
      
      // tab 标题。语言判出来之前先用**英文**（国际默认），QuestData 一到就会自我纠正
      // （PopulateTabs 里先建 tab，OnQuestDataUpdate 里再刷一次标题）。
      // 载荷里的 T 行是保留字段：语言未知时用它给的英文标题。
      private function SaqTabTitle() : String
      {
         if(this.SaqLangKnown)
         {
            return this.SaqLangZh ? SAQ_TITLE_ZH : SAQ_TITLE_EN;
         }
         if(this.SaqTitleEn != null && this.SaqTitleEn.length > 0)
         {
            return this.SaqTitleEn;
         }
         return SAQ_TITLE_EN;
      }
      
      private function SaqApplyTabTitle() : void
      {
         this.SetAvailableTabText(this.SaqTabTitle());
      }
      
      private function SaqEmbeddedPayload() : String
      {
         if(SAQ_EMBEDDED_CHUNKS == null || SAQ_EMBEDDED_CHUNKS.length == 0)
         {
            return null;
         }
         return SAQ_EMBEDDED_CHUNKS.join("");
      }
      
      // 解析载荷 -> 与语言无关的原始条目（名字中英都留着，取用时再按语言选）
      private function SaqParsePayload(param1:String) : Array
      {
         var _loc2_:Array = new Array();
         if(param1 == null)
         {
            return _loc2_;
         }
         var _loc3_:Array = param1.split("\n");
         var _loc4_:int = 0;
         while(_loc4_ < _loc3_.length)
         {
            var _loc5_:String = _loc3_[_loc4_];
            if(_loc5_.length > 2)
            {
               if(_loc5_.substr(0,2) == "T\t")
               {
                  var _loc6_:Array = _loc5_.substr(2).split("\t");
                  if(_loc6_.length > 0)
                  {
                     this.SaqTitleZh = _loc6_[0];
                     this.SaqTitleEn = _loc6_[_loc6_.length - 1];
                  }
               }
               else if(_loc5_.substr(0,2) == "Q\t")
               {
                  var _loc7_:Array = _loc5_.substr(2).split("\t");
                  if(_loc7_.length >= 3)
                  {
                     _loc2_.push({
                        "uID":parseInt(_loc7_[0]),
                        "iType":parseInt(_loc7_[1]),
                        "sNameZh":_loc7_[2],
                        "sNameEn":_loc7_.length >= 4 ? _loc7_[3] : _loc7_[2]
                     });
                  }
               }
            }
            _loc4_++;
         }
         return _loc2_;
      }
      
      // 原始条目 -> 任务列表条目。
      //
      // 字段必须**覆盖引擎推的 QuestData 条目所拥有的一切**：UI 各处会直接读，
      // 少一个就可能抛 Error #1010（实测 MissionInfo.UpdateMissionInfo 会读
      // `param1.sDescription.length`，所以哪怕没有简介也必须给空串）。
      // 原始类型 -> UI 能安全渲染的类型。
      // 原版 QuestUtils.GetQuestIconLabel 只对「活动(0)/杂项(3)/任务(4)」返回真实图标名，
      // 派系(2)/主线(1) 会落到 default -> "None"，而 FactionSymbols 里未必有 "None" 这一帧
      // —— gotoAndStop 找不到帧会抛异常，把整行（甚至整列表）的渲染带崩。
      // 静态表里存在的就是 0/2/3/4，所以只把 2 归一成 4（派系任务按「任务」图标显示）。
      private static function SaqSafeType(param1:int) : int
      {
         if(param1 == QuestUtils.ACTIVITY_QUEST_TYPE || param1 == QuestUtils.MISC_QUEST_TYPE || param1 == QuestUtils.MISSION_QUEST_TYPE)
         {
            return param1;
         }
         return QuestUtils.MISSION_QUEST_TYPE;
      }
      
      // 我们的条目带的「目标（阶段）」：一条静态文案。字段按 MissionsListEntry.SetEntryText /
      // ShowObjective 的读取清单给全（sName / iRemainingTime / bComplete / bActive /
      // bFailed / bIsMiscObjective / bCanShowOnMap）—— 少一个都可能渲染出问题。
      // 注意：**不能**带 aObjectives 属性（IsMission 的判据是 hasOwnProperty("aObjectives")，
      // 带了它这条子条目就会被当成"任务"）。
      private function SaqBuildObjective(param1:Object) : Object
      {
         return {
            "uID":param1.uID,
            "uOwnerQuestFormID":param1.uID,
            "uIndex":0,
            "uInstanceID":0,
            "iType":SaqSafeType(param1.iType),
            "iFaction":FactionUtils.FACTION_NONE,
            "sName":this.SaqUseChinese() ? "前往接取地点" : "Reach the pickup location",
            "sDescription":"",
            "bComplete":false,
            "bFailed":false,
            "bActive":false,
            "bIsMiscObjective":false,
            "bCanShowOnMap":false,
            "iRemainingTime":-1,
            // ★ 第 14 轮：子项也带 SAQ 标记 —— 让 SaqIsOurEntry() 对主标题与子项**都**成立，
            //   交互才能与原版对齐（原版：点子项 = 追踪切换；点主标题 = 展开/收起）。
            "bSaqAvailable":true
         };
      }
      
      // 右侧详情面板里的描述文案（固定内容，告诉玩家这条记录怎么用）。
      // 键名从当前控制映射动态取（与底部按钮栏同一来源：键盘 = R「设定航线」，手柄 = 手柄 X 键）。
      // ★ 第 15 轮修正：不要写死键名 —— 事件名 "XButton" 是**手柄 X 按钮**，键盘下它映射到 R，
      //   写死「X 键」会让提示指向一个游戏里不存在的交互。
      private function SaqDescriptionText() : String
      {
         var _loc1_:String = "";
         try
         {
            if(this.KeyHelper != null)
            {
               _loc1_ = this.KeyHelper.GetButtonNameForEvent("XButton","");
            }
         }
         catch(_loc2_:Error)
         {
            _loc1_ = "";
         }
         if(_loc1_.length == 0)
         {
            return this.SaqUseChinese()
               ? "这条任务当前可以接取。展开后选中目标，或使用底部的「设定航线」即可引导到接取地点。"
               : "This quest is currently available. Expand it, then select the objective or use SET COURSE to be guided to the pickup location.";
         }
         return this.SaqUseChinese()
            ? "这条任务当前可以接取。展开后选中目标，或按 " + _loc1_ + "（设定航线）即可引导到接取地点。"
            : "This quest is currently available. Expand it, then select the objective or press " + _loc1_ + " (SET COURSE) to be guided to the pickup location.";
      }
      
      private function SaqBuildEntry(param1:Object) : Object
      {
         return {
            "uID":param1.uID,
            "uInstanceID":0,
            "iType":SaqSafeType(param1.iType),
            "iFaction":FactionUtils.FACTION_NONE,
            "sName":this.SaqUseChinese() ? param1.sNameZh : param1.sNameEn,
            "sDescription":this.SaqDescriptionText(),
            // 引导中的那条保持「追踪中」的视觉（左侧竖条）—— 列表重建（SaqRefresh）后不丢状态。
            "bActive":this.SaqGuideQuest != 0 && param1.uID == this.SaqGuideQuest,
            "bComplete":false,
            "bFailed":false,
            "bCanBeRejected":false,
            "bIsMiscQuest":false,
            "bIsMiscObjective":false,
            "bCanShowOnMap":false,
            "iRemainingTime":-1,
            // ★ 第 12 轮：带一条「目标（阶段）」——玩家反馈「看不到任务阶段，没法像原版
            //   任务那样展开看内容」。原版 MissionsList 展开子条目 = aObjectives
            //   （见 MissionsList.GetChildrenOfEntry），空数组时条目就是个没有阶段的死条目。
            "aObjectives":[this.SaqBuildObjective(param1)],
            // ★ 可见性标记（MissionsList.EntryFilterCompare_Impl 里唯一认它的判据）：
            //   iType 保留原始任务类型给图标/类型文本用，**不能**再靠 iType 决定
            //   是否出现在「可接任务」tab（那是上一轮列表空的根因）。
            "bSaqAvailable":true
         };
      }
      
      // 解析 + 建条目 + 过滤掉玩家已知任务 + 合并进任务列表 + 刷新 tab 标题
      private function SaqRefresh() : int
      {
         if(this.SaqRawQuests == null)
         {
            var _loc1_:String = this.SaqSourceIsCpp ? this.SaqSourcePayload : this.SaqEmbeddedPayload();
            this.SaqRawQuests = this.SaqParsePayload(_loc1_);
         }
         var _loc2_:Array = new Array();
         var _loc3_:int = 0;
         while(_loc3_ < this.SaqRawQuests.length)
         {
            _loc2_.push(this.SaqBuildEntry(this.SaqRawQuests[_loc3_]));
            _loc3_++;
         }
         this.RawAvailableQuests = _loc2_;
         this.AvailableQuests = this.FilterKnownQuests(_loc2_);
         this.SaqAutoCancelIfAccepted();
         this.SaqApplyTabTitle();
         if(this.MissionsList_mc != null)
         {
            // 把列表掩码与本菜单当前选中的 tab 对齐一次。
            // （BSScrollingTree 的默认掩码是 0xFFFFFFFF；如果这一帧还没人设置过它，
            //   「全部」tab 会用 0xFFFFFFFF 放行 bSaqAvailable 条目的判据 —— 这里先对齐，
            //   保证重建列表时用的是当前 tab 的真实掩码。）
            this.SaqSyncListMask();
            this.MissionsList_mc.InitializeEntries(this.BuildMergedList());
            this.SaqSnapshotTab("refresh");
            if(this.visible)
            {
               this.onMissionSelectionChange();
            }
         }
         return _loc2_.length;
      }
      
      private function SaqSyncListMask() : void
      {
         var _loc1_:int = this.TabbedFilterSelection_mc != null ? int(this.TabbedFilterSelection_mc.selectedIndex) : -1;
         if(_loc1_ >= 0 && _loc1_ < this.FilterInfoA.length)
         {
            this.MissionsList_mc.filterMask = this.FilterInfoA[_loc1_].flag;
         }
      }
      
      // 界面快照（第 9 轮）：在「切 tab」和「重建列表」这两个时刻记下
      // 「tab 序号 / 掩码 / 当前列表条数」。
      //
      // 为什么要有它：C++ 侧只能在推送那一刻读一次 SAQ_Report，而那时玩家还没切到
      // 我们那个 tab（实测 tab=0、mask=0xFFFFFFBF）—— 于是「我们 tab 里到底有几条」
      // 在日志里始终是空白。加上这个快照后，只要玩家**碰过**我们那个 tab，
      // 无论他之后切到哪里，SAQ_Report 都会把那一刻的状态带出来。
      private function SaqSnapshotTab(param1:String) : void
      {
         if(this.MissionsList_mc == null || this.TabbedFilterSelection_mc == null || this.FilterInfoA == null)
         {
            return;
         }
         var _loc2_:int = int(this.TabbedFilterSelection_mc.selectedIndex);
         var _loc3_:int = int(this.MissionsList_mc.filterMask);
         var _loc4_:int = int(this.MissionsList_mc.entryCount);
         var _loc5_:String = "tab=" + _loc2_ + " mask=0x" + (_loc3_ >>> 0).toString(16) + " list=" + _loc4_;
         this.SaqTabProbe = param1 + "[" + _loc5_ + "]";
         if(_loc2_ == this.FilterInfoA.length - 1)
         {
            this.SaqOurTabProbe = _loc5_;
            if(_loc4_ > this.SaqOurTabMaxList)
            {
               this.SaqOurTabMaxList = _loc4_;
            }
         }
      }
      
      // ==================================================================
      //  把 SAQ 入口挂到 SWF 的 root 上 —— 这是 C++ 推送能用起来的关键。
      //
      //  背景：C++ 侧只能通过 ASMovieRoot::Invoke("A.B.C") 调 AS3，而路径解析
      //  **从 root 开始**。MissionMenu 这个类（Embed 自 assets.swf 的 symbol94）
      //  是主时间轴上的**子元件**，不是 root 本身，所以
      //  "SetAvailableQuests" / "_root.SetAvailableQuests" / "_root.root.…"
      //  在 root 上都找不到 —— 日志里就是六种组合全 fail。
      //  在 root（MainTimeline，dynamic 的 MovieClip）上挂一份函数引用后，
      //  C++ 调 "SAQ_SetAvailableQuests" 就能直达本实例。
      // ==================================================================
      private function SaqPublishEntryPoint() : void
      {
         try
         {
            var _loc1_:Object = this.root;
            if(_loc1_ != null && _loc1_ != this)
            {
               _loc1_["SAQ_SetAvailableQuests"] = this.SetAvailableQuests;
               _loc1_["SAQ_Probe"] = this.SAQ_Probe;
               _loc1_["SAQ_ApplyPayload"] = this.SAQ_ApplyPayload;
               _loc1_["SAQ_Report"] = this.SAQ_Report;
               _loc1_["SAQ_PeekGuide"] = this.SAQ_PeekGuide;
               // ★ 第 16 轮：C++ → 界面的两条回写通道
               //   SAQ_GuideReply     = 引导请求的处理结果（成功/没有引导目标/写失败）
               //   SAQ_SyncGuideState = 菜单打开后同步「当前实际引导任务」
               _loc1_["SAQ_GuideReply"] = this.SAQ_GuideReply;
               _loc1_["SAQ_SyncGuideState"] = this.SAQ_SyncGuideState;
            }
         }
         catch(e:Error)
         {
         }
      }
      
      // C++ 插件入口：Invoke("SetAvailableQuests", <载荷>)。
      // 返回值约定（C++ 侧据此判断协议有没有通）：
      //   >0  = 解析成功（值是解析到的条数）
      //   -1  = 参数是 null/空串（★ 参数没传过来 / 传成空）
      //   -2  = 参数非空但解析不出条目（编码/格式问题）★ 此时自动回退内嵌表
      // 返回「解析出来的」条数而不是过滤后的数量：一旦任务全被 QuestData 滤掉就成 0，
      // C++ 会误判「协议没通」，白试剩下几种组合。
      public function SetAvailableQuests(param1:String) : int
      {
         if(param1 == null || param1.length == 0)
         {
            return -1;
         }
         this.SaqSourcePayload = param1;
         this.SaqSourceIsCpp = true;
         this.SaqRawQuests = null;
         var _loc2_:int = this.SaqRefresh();
         if(_loc2_ <= 0)
         {
            this.SaqSourceIsCpp = false;
            this.SaqRawQuests = null;
            this.SaqRefresh();
            return -2;
         }
         return _loc2_;
      }
      
      // C++ 诊断入口：把收到的字符串长度 + 前缀原样返回。
      // 用途：Invoke 的参数如果没传对（编码/截断/NUL），这条一眼能看出来。
      public function SAQ_Probe(param1:String) : String
      {
         if(param1 == null)
         {
            return "null";
         }
         return param1.length + "|" + param1.substr(0,24);
      }
      
      // C++ 备用入口（SetVariable 通路）：载荷先放到 root 的 SAQ_Payload 变量上，
      // 这里无参调用 —— 绕开「Invoke 带参数」这条链路的潜在问题。
      public function SAQ_ApplyPayload() : int
      {
         var _loc1_:* = this.root["SAQ_Payload"];
         if(_loc1_ == null)
         {
            return -1;
         }
         return this.SetAvailableQuests(String(_loc1_));
      }
      
      // C++ 诊断入口（**只读**，不改任何状态）：把本实例当前的关键状态回读成一行字符串。
      //
      // 为什么需要它：第 7 轮实测日志里「推送成功 + 返回 0」，靠日志**无法判断**
      // 界面到底有没有按推送的数据渲染（返回 0 其实是 C++ 读 int 的方式错了），
      // 只能靠肉眼看游戏 —— 这一条把这个缺口补上：日志里直接给出
      //   「解析到几条 / 过滤后剩几条 / 列表里几条 / 当前掩码 / 选中 tab / 语言 / 标题」。
      //
      // 字段含义：
      //   src       = 数据源（cpp = C++ 推送；embedded = SWF 内嵌回退表）
      //   raw       = 载荷解析出的条数（-1 = 还没解析过）
      //   keep      = 滤掉「玩家已知任务」后剩下的条数（-1 = 空）
      //   questData = 引擎推给 UI 的任务条数（语言判定与已知任务过滤都靠它）
      //   list      = 列表当前实际条目数（含引擎推的任务 + 我们的条目）
      //   mask      = 列表当前过滤掩码（我们 tab 应该是 0x40）
      //   tab       = 当前选中的 tab 序号（我们的是最后一个 = 7）
      //   lang      = 语言判定结果
      //   title     = 我们那个 tab 此刻的标题
      //   last      = 最近一次「切 tab / 重建列表」时的界面快照（第 9 轮）
      //   ourTab    = 我们那个 tab 被选中时的最后一次快照（没碰过就是 "-"）
      //   ourTabMax = 我们那个 tab 上见过的最大条目数（-1 = 没碰过）
      public function SAQ_Report() : String
      {
         var _loc1_:int = this.SaqRawQuests != null ? this.SaqRawQuests.length : -1;
         var _loc2_:int = this.AvailableQuests != null ? this.AvailableQuests.length : -1;
         var _loc3_:int = this.QuestData != null ? this.QuestData.length : -1;
         var _loc4_:int = this.MissionsList_mc != null ? int(this.MissionsList_mc.entryCount) : -1;
         var _loc5_:int = this.MissionsList_mc != null ? int(this.MissionsList_mc.filterMask) : -1;
         var _loc6_:int = this.TabbedFilterSelection_mc != null ? int(this.TabbedFilterSelection_mc.selectedIndex) : -1;
         var _loc7_:String = this.SaqLangKnown ? (this.SaqLangZh ? "zh" : "en") : "?";
         // ★ 掩码按**无符号**十六进制打（第 8 轮实测打出来是 `0x-41`，即 -0x41 = 0xFFFFFFBF，
         //   看日志的人得自己心算补码；>>> 0 转成 uint 后就是 0xffffffbf）。
         var _loc8_:String = "src=" + (this.SaqSourceIsCpp ? "cpp" : "embedded")
            + " raw=" + _loc1_
            + " keep=" + _loc2_
            + " questData=" + _loc3_
            + " list=" + _loc4_
            + " mask=0x" + (_loc5_ >>> 0).toString(16);
         _loc8_ += " tab=" + _loc6_
            + " lang=" + _loc7_
            + " title=" + this.SaqTabTitle()
            + " visible=" + (this.visible ? "1" : "0");
         _loc8_ += " last=" + this.SaqTabProbe + " ourTab=" + this.SaqOurTabProbe + " ourTabMax=" + this.SaqOurTabMaxList;
         _loc8_ += " guide=" + this.SaqGuideSeq + "|" + this.SaqGuideQuest + "|" + this.SaqGuideNote;
         // 玩家任务日志名单（第 11 轮，诊断用）：QuestData 的「FormID:名字」，最多 12 条。
         // 用途：玩家说「某条可接任务没找到」时，先看它是不是**已经在玩家日志里**
         // （那样它被 C++/AS3 两层过滤中的某一层正当挡掉）—— 在这个名单里一查便知。
         // 例：qdata[9]=[2ad3d5:全数到期,...] ⇒ 玩家其实已经接过这条任务。
         var _loc9_:String = "";
         if(this.QuestData != null)
         {
            var _loc10_:int = 0;
            while(_loc10_ < this.QuestData.length && _loc10_ < 12)
            {
               if(_loc10_ > 0)
               {
                  _loc9_ += ",";
               }
               _loc9_ += this.QuestData[_loc10_].uID.toString(16) + ":" + this.QuestData[_loc10_].sName;
               _loc10_++;
            }
         }
         _loc8_ += " qdata[" + _loc3_ + "]=[" + _loc9_ + "]";
         // ★ 第 19 轮：被过滤名单（raw 与 keep 的差是哪几条）。放在 qdata **之后**，
         //   但 qdata 最多 12 条 —— 若报告被长度上限截断，先保 qdata（玩家可对照的名字），
         //   drop 只是纯 uID 十六进制（通常 0~5 条），实际几乎不会被截到。
         _loc8_ += " drop[" + this.SaqDropCount + "]=[" + this.SaqDropList + "]";
         return _loc8_;
      }
      
      // ==================================================================
      //  引导（第 10 轮）
      //
      //  未接取的任务引擎不给标记（它只在「正在运行 + 有已显示目标」时才画），所以引导
      //  走我们自己的代理任务：C++ 侧轮询 SAQ_PeekGuide()，把目标引用写进 ESM 的 GLOB，
      //  Papyrus 那边套到代理任务的别名上。AS3 这一层只负责「玩家想让哪条任务被引导」。
      // ==================================================================
      private function SaqIsOurEntry(param1:Object) : Boolean
      {
         return param1 != null && param1.bSaqAvailable == true;
      }
      
      // 条目的显示名：选中的如果是**子项**（「前往接取地点」），名字取它的父任务名 ——
      // 日志/提示里说「已设为引导:<任务名>」才有意义（子项的名字对玩家没有信息量）。
      private function SaqQuestName(param1:Object) : String
      {
         if(param1 == null)
         {
            return "?";
         }
         if(MissionsListEntry.IsMission(param1))
         {
            return param1.sName;
         }
         var _loc2_:Object = this.FindQuestEntryByID(this.AvailableQuests, param1.uID);
         return _loc2_ != null ? _loc2_.sName : param1.sName;
      }
      
      // ★ 第 17 轮：被引导的任务一旦进了玩家任务日志（= 玩家已经接到它了），引导自己消失。
      //
      //   为什么需要：引导是「借」代理任务（SAQ_MainQuest）画出来的 —— 玩家真的接到任务后，
      //   代理任务还挂着「追踪中」，于是 ① HUD 上继续指着那个地点（已经没用了）；
      //   ② 玩家任务日志里一直躺着一条名叫「可接任务」的代理任务。
      //   判据只用**玩家任务日志**（QuestData 里有这个 uID）——这是「已接取」的权威数据
      //   （第 11 轮的结论：TESQuest 的 started 位不算数，见 docs/99 第十一节）。
      //   动作 = 序号 +1、目标清 0（和玩家自己按「取消」走同一条路，DLL 侧无需新协议）。
      private function SaqAutoCancelIfAccepted() : void
      {
         if(this.SaqGuideQuest == 0 || this.QuestData == null)
         {
            return;
         }
         var _loc1_:int = 0;
         while(_loc1_ < this.QuestData.length)
         {
            var _loc2_:Object = this.QuestData[_loc1_];
            if(_loc2_ != null && Number(_loc2_.uID) == this.SaqGuideQuest)
            {
               var _loc3_:Number = this.SaqGuideQuest;
               this.SaqGuideSeq = this.SaqGuideSeq + 1;
               this.SaqGuideQuest = 0;
               this.SaqGuideNote = "已接取，自动取消引导";
               this.SaqApplyTrackedMarker(_loc3_, 0);
               return;
            }
            _loc1_++;
         }
      }
      
      // 切换引导：同一条再按一次 = 取消（返回 true 表示现在是「已设为引导」）。
      private function SaqToggleGuide(param1:Object) : Boolean
      {
         if(!SaqIsOurEntry(param1))
         {
            return false;
         }
         var _loc2_:Number = this.SaqGuideQuest == param1.uID ? 0 : param1.uID;
         var _loc3_:Number = this.SaqGuideQuest;
         this.SaqGuideSeq = this.SaqGuideSeq + 1;
         this.SaqGuideQuest = _loc2_;
         if(_loc2_ != 0)
         {
            GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
            this.SaqGuideNote = "已设为引导:" + this.SaqQuestName(param1);
         }
         else
         {
            GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
            this.SaqGuideNote = "已取消引导";
         }
         // ★ 第 13 轮：把「引导中」映射到条目的 bActive —— 列表左侧那条竖条
         //   （TrackIndicator）会像原版「追踪中」的任务一样亮起来。玩家反馈：
         //   我们的条目看起来「永远没被选中」，缺少这个视觉反馈。
         this.SaqApplyTrackedMarker(_loc3_, _loc2_);
         return _loc2_ != 0;
      }
      
      // 把「当前引导的任务」写进条目的 bActive，并就地刷新受影响的条目。
      //
      // ★ 第 14 轮修正刷新方式：原来按「数据下标」调 UpdateEntry(QuestData.length + i)，
      //   但列表的**显示下标**并不等于数据下标 —— MissionsList.InitializeEntries 会把
      //   「已完成」条目挪到最后、把 misc 条目挪到末尾，展开时子项还会插进来；
      //   而且 BSScrollingList 根本没有 UpdateEntry 这个接口（那次调用实际被 try 吞掉了）。
      //   现在改成把「要刷新的任务 uID」交给 MissionsList.SAQ_RefreshQuestRow()：
      //   它在**当前显示列表**里按 uID 找行（含已展开的子项），只重渲染找到的那几行，
      //   不动滚动位置、不动展开状态。
      private function SaqApplyTrackedMarker(param1:Number, param2:Number) : void
      {
         if(this.AvailableQuests == null || this.MissionsList_mc == null)
         {
            return;
         }
         var _loc3_:int = 0;
         while(_loc3_ < this.AvailableQuests.length)
         {
            var _loc4_:Object = this.AvailableQuests[_loc3_];
            if(_loc4_ != null && (_loc4_.uID == param1 || _loc4_.uID == param2))
            {
               _loc4_.bActive = param2 != 0 && _loc4_.uID == param2;
               this.MissionsList_mc.SAQ_RefreshQuestRow(_loc4_.uID);
            }
            _loc3_++;
         }
      }
      
      // C++ 侧入口（无参）："<序号>|<任务FormID>"。序号 0 = 还没有请求；
      // 序号变化才算一次新请求（C++ 侧据此去重）。
      public function SAQ_PeekGuide() : String
      {
         return this.SaqGuideSeq + "|" + this.SaqGuideQuest;
      }
      
      // 按 uID 找一条可接任务的显示名（引导相关文案用；找不到给 "?"）。
      private function SaqQuestNameByID(param1:Number) : String
      {
         var _loc2_:Object = this.FindQuestEntryByID(this.AvailableQuests, param1);
         if(_loc2_ != null)
         {
            return _loc2_.sName;
         }
         return "?";
      }
      
      // ==================================================================
      //  C++ → 界面 · 回写通道（第 16 轮）
      //
      //  为什么需要它：SaqToggleGuide 只能在本地「立刻」切状态（音效 / 竖条 / 文案），
      //  但「这条任务到底有没有引导目标」只有 C++ 侧知道（静态表里的 guideRef）。
      //  没有回写时，玩家点到**没有引导目标**的任务（202 条里 34 条）会看到
      //  「已设为引导」，实际什么都没发生 —— 而且旧引导如果还在，游戏里指的仍是旧任务。
      //
      //  协议："<seq>|<实际引导任务FormID>|<结果码>"
      //    结果码：0=成功 / 1=该任务没有引导目标 / 2=写 ESM 通道失败 / 3=静态表里没有这条
      //           ★ 第 19 轮新增 4 = 引导未生效（脚本确认超时 / 别名不存在）——
      //           C++ 侧做过确认（PollGuideVerify）后仍未生效，必须回滚界面，
      //           否则界面会一直显示「已设为引导」而世界里什么都没有（界面说谎）。
      //  语义：**以「实际值」为准**——界面把 SaqGuideQuest 对齐到 C++ 报的实际值，
      //  与本地状态不一致时就是「被拒绝」，回滚竖条并给出失败文案。
      // ==================================================================
      public function SAQ_GuideReply(param1:String) : String
      {
         if(param1 == null)
         {
            return "bad";
         }
         var _loc2_:Array = param1.split("|");
         if(_loc2_.length < 3)
         {
            return "bad";
         }
         var _loc3_:int = int(_loc2_[0]);
         if(_loc3_ != this.SaqGuideSeq)
         {
            // 玩家已经又点了别的（或界面换代）—— 过期应答，忽略。
            return "stale";
         }
         var _loc4_:Number = Number(_loc2_[1]);
         var _loc5_:int = int(_loc2_[2]);
         var _loc6_:Number = this.SaqGuideQuest;
         if(_loc4_ == _loc6_ && _loc5_ == 0)
         {
            // 成功且状态一致：本地早已切好（音效/文案/竖条都不动）
            return "same";
         }
         this.SaqGuideQuest = _loc4_;
         if(_loc5_ == 0)
         {
            this.SaqGuideNote = _loc4_ != 0 ? "已设为引导:" + this.SaqQuestNameByID(_loc4_) : "已取消引导";
         }
         else
         {
            // 被拒绝：回滚到「实际值」，给失败反馈（OFF 音 = 与原版「取消追踪」同款提示）
            GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
            if(_loc5_ == 1)
            {
               this.SaqGuideNote = "该任务暂无引导目标";
            }
            else if(_loc5_ == 2)
            {
               this.SaqGuideNote = "引导通道写入失败";
            }
            else if(_loc5_ == 4)
            {
               // ★ 第 19 轮：脚本没响应（确认超时 / 别名不存在）——必须回滚。
               this.SaqGuideNote = "引导未生效:脚本未响应";
            }
            else
            {
               this.SaqGuideNote = "引导失败:任务不在静态表";
            }
         }
         this.SaqApplyTrackedMarker(_loc6_, _loc4_);
         return "ok";
      }
      
      // ==================================================================
      //  C++ → 界面 · 状态同步（第 16 轮）
      //
      //  菜单每次打开都是**新的 SWF 实例**（SaqGuideQuest 归 0），而引导可能还在生效
      //  （蓝点还指着某个地方）。不同步的话有两个毛病：
      //    ① 列表重建时 SaqBuildEntry 的 bActive 读 0 ⇒ 引导中那条的竖条丢了；
      //    ② 对「正在引导的那条」第一次点击会被算成「设置引导」而不是「取消」。
      //  只在玩家还没操作过（SaqGuideSeq == 0）时接受同步 —— 否则会覆盖玩家刚做的操作
      //  （那种情况的结果由 SAQ_GuideReply 回来）。
      // ==================================================================
      public function SAQ_SyncGuideState(param1:String) : String
      {
         if(this.SaqGuideSeq != 0)
         {
            return "skip";
         }
         var _loc2_:Number = Number(param1);
         var _loc3_:Number = this.SaqGuideQuest;
         if(_loc2_ == _loc3_)
         {
            return "same";
         }
         this.SaqGuideQuest = _loc2_;
         this.SaqGuideNote = _loc2_ != 0 ? "当前引导:" + this.SaqQuestNameByID(_loc2_) : "-";
         this.SaqApplyTrackedMarker(_loc3_, _loc2_);
         return "ok";
      }
      
      private function OnQuestDataUpdate(param1:FromClientDataEvent) : void
      {
         this.QuestData = param1.data.aQuests;
         if(this.RawAvailableQuests != null)
         {
            this.AvailableQuests = this.FilterKnownQuests(this.RawAvailableQuests);
         }
         this.CollapseAllChildren();
         this.lastSelectedIndex = -1;
         // 任务名到手了 —— 语言判定与「已接任务」过滤都在这里一并重算
         // （SaqRefresh 内部会 InitializeEntries(BuildMergedList())）
         this.SaqRefresh();
         if(this.visible)
         {
            stage.focus = this.MissionsList_mc;
            if(this.QuestData.length > 0 && this.MissionsList_mc.selectedIndex == -1)
            {
               this.MissionsList_mc.selectedIndex = 0;
            }
            if(this.scrollPositionAtTracking)
            {
               this.MissionsList_mc.scrollPosition = this.scrollPositionAtTracking;
            }
            this.scrollPositionAtTracking = -1;
            this.onMissionSelectionChange();
         }
         else
         {
            this.MissionsList_mc.selectedIndex = -1;
         }
         this.InitializeLastState();
      }
      
      public function onStickDataChanged(param1:FromClientDataEvent) : *
      {
         this.MissionInfo_mc.ProcessStickData(param1);
      }
      
      public function onMissionMenuStateData(param1:FromClientDataEvent) : *
      {
         this.StoredLastOpenedIds = param1.data.aOpenQuestIds;
         this.StoredLastCategory = param1.data.uCategoryIndex;
         this.SetQTDisplayFlag(param1.data.bShowOnlyActiveQTs);
         this.InitializeLastState();
      }
      
      public function onFireForgetEvent(param1:FromClientDataEvent) : *
      {
         if(GlobalFunc.HasFireForgetEvent(param1.data,"MissionMenu_TransitionToMap"))
         {
            this.CloseMenu(false);
         }
      }
      
      override public function onAddedToStage() : void
      {
         super.onAddedToStage();
         BSUIDataManager.Subscribe("QuestData",this.OnQuestDataUpdate);
         BSUIDataManager.Subscribe("MissionMenuStickData",this.onStickDataChanged);
         BSUIDataManager.Subscribe("MissionMenuStateData",this.onMissionMenuStateData);
         BSUIDataManager.Subscribe("FireForgetEventData",this.onFireForgetEvent);
         GlobalFunc.PlayMenuSound("UIMenuMissionsMenuEnter");
         this.KeyHelper = new ButtonKeyHelper();
         // root 上挂一份 C++ 插件用的入口（见 SaqPublishEntryPoint 注释）
         this.SaqPublishEntryPoint();
      }
      
      override protected function OnPlatformChanged(param1:Object) : void
      {
         super.OnPlatformChanged(param1);
         this.TabbedFilterSelection_mc.Configure(CategoryTab,BSTabbedSelection.CENTER_ALIGNED,BSTabbedSelection.DEFAULT_SPACING,uiController == PlatformUtils.PLATFORM_PC_KB_MOUSE ? ["LShoulder","Left"] : ["LShoulder"],uiController == PlatformUtils.PLATFORM_PC_KB_MOUSE ? ["RShoulder","Right"] : ["RShoulder"]);
      }
      
      private function onFilterChanged(param1:BSTabbedSelectionEvent) : *
      {
         this.bSkipSelectionSounds = true;
         this.CollapseAllChildren();
         this.MissionsList_mc.filterMask = this.currentFilterFlag;
         if(this.MissionsList_mc.entryCount > 0)
         {
            this.MissionsList_mc.selectedIndex = 0;
         }
         GlobalFunc.PlayMenuSound(MISSION_CATEGORY_CHANGE_SOUND);
         this.bSkipSelectionSounds = false;
         this.SaqSnapshotTab("switch");
      }
      
      private function CollapseAllChildren() : *
      {
         this.bCollapsing = true;
         if(this.bWithinMiscQuest)
         {
            this.MissionsList_mc.ShowEntryChildren(this.miscQuestIndex,false);
         }
         else
         {
            this.MissionsList_mc.ShowEntryChildren(this.lastSelectedIndex,false);
         }
         this.lastSelectedIndex = -1;
         this.bCollapsing = false;
      }
      
      public function ProcessUserEvent(param1:String, param2:Boolean) : Boolean
      {
         var _loc3_:Boolean = false;
         if(param1 == "ReturnToStarMap" && param2 == false)
         {
            this.OnCancelEvent();
            _loc3_ = true;
         }
         else if(param1 == "Missions" && param2 == false)
         {
            this.onCloseSubMenuToGame();
            _loc3_ = true;
         }
         _loc3_ = this.ButtonBar_mc.ProcessUserEvent(param1,param2);
         if(!_loc3_)
         {
            _loc3_ = this.TabbedFilterSelection_mc.ProcessUserEvent(param1,param2);
         }
         return _loc3_;
      }
      
      private function SetQTDisplayFlag(param1:Boolean) : void
      {
         if(this.ShowOnlyActiveQTs != param1)
         {
            this.ShowOnlyActiveQTs = param1;
            this.ToggleQTDisplayButton.SetButtonData(this.ShowOnlyActiveQTs ? this.ShowAllQTsBtnData : this.ShowOnlyActiveQTsBtnData);
         }
      }
      
      private function ToggleQTDisplay() : void
      {
         BSUIDataManager.dispatchEvent(new Event("MissionMenu_ToggleQTDisplay"));
      }
      
      // 按 uID 在一份条目数组里找主条目（找不到给 null）。
      private function FindQuestEntryByID(param1:Array, param2:Number) : Object
      {
         if(param1 == null)
         {
            return null;
         }
         var _loc3_:int = 0;
         while(_loc3_ < param1.length)
         {
            if(param1[_loc3_] != null && param1[_loc3_].uID == param2)
            {
               return param1[_loc3_];
            }
            _loc3_++;
         }
         return null;
      }
      
      private function GetParentMissionData(param1:Object) : Object
      {
         if(param1 == null)
         {
            return null;
         }
         if(MissionsListEntry.IsMission(param1))
         {
            return param1;
         }
         if(param1.bIsMiscObjective != null && param1.bIsMiscObjective !== false)
         {
            return null;
         }
         var _loc2_:Object = this.FindQuestEntryByID(this.QuestData,param1.uOwnerQuestFormID);
         // ★ 第 14 轮：我们的可接任务在引擎/玩家日志里都不存在（还没接取），
         //   只在本菜单的 AvailableQuests 里 —— 子项要能找到父任务，右侧详情面板
         //   才会像原版那样显示这条任务的内容。
         if(_loc2_ == null)
         {
            _loc2_ = this.FindQuestEntryByID(this.AvailableQuests,param1.uOwnerQuestFormID);
         }
         return _loc2_;
      }
      
      public function onMissionSelectionChange() : *
      {
         var _loc1_:Object = this.MissionsList_mc.selectedEntry;
         var _loc2_:Boolean = _loc1_ != null ? MissionsListEntry.IsMission(_loc1_) : false;
         var _loc3_:Object = null;
         if(!_loc2_)
         {
            _loc3_ = this.GetParentMissionData(_loc1_);
         }
         if(_loc1_ != null)
         {
            this.CanTrackOrUntrack = !_loc2_;
            if(this.CanTrackOrUntrack)
            {
               if(_loc3_ == null || _loc3_.uID == 0)
               {
                  this.CanTrackOrUntrack = Boolean(_loc1_.bIsMiscObjective) && !_loc1_.bComplete;
               }
               else
               {
                  this.CanTrackOrUntrack = !_loc3_.bComplete;
               }
            }
            this.UpdateRejectData(_loc1_.bCanBeRejected === true && (_loc3_ == null || _loc3_.uID == 0));
            this.ShowOnMapButton.Enabled = MissionsListEntry.CanShowOnMap(_loc1_) != 0;
            this.PlotToLocationButton.Enabled = MissionsListEntry.CanShowOnMap(_loc1_) != 0;
            if(this.SaqIsOurEntry(_loc1_))
            {
               // 「可接任务」条目：原版没有它的位置数据（Y 显示在地图上不给用），
               // SET COURSE（键盘 R / 手柄 X）改用我们自己的引导 —— 见 OnPlotCourseEvent。
               this.ShowOnMapButton.Enabled = false;
               this.PlotToLocationButton.Enabled = true;
            }
            if(_loc2_ || _loc1_.bIsMiscObjective === true)
            {
               this.MissionInfo_mc.UpdateMissionInfo(this.MissionsList_mc.selectedEntry);
            }
            else if(_loc3_)
            {
               this.MissionInfo_mc.UpdateMissionInfo(_loc3_);
            }
         }
         else
         {
            this.ShowOnMapButton.Enabled = false;
            this.PlotToLocationButton.Enabled = false;
            this.CanTrackOrUntrack = false;
            this.UpdateRejectData(false);
         }
         if(_loc2_)
         {
            this.lastSelectedIndex = this.MissionsList_mc.selectedIndex;
         }
         if(!this.bSkipSelectionSounds)
         {
            GlobalFunc.PlayMenuSound(MISSION_SELECTION_CHANGE_SOUND);
            GlobalFunc.PlayMenuSound(MISSION_SUBTASK_TOGGLE_SOUND);
         }
         this.bSkipSelectionSounds = false;
      }
      
      override protected function OnControlMapChanged(param1:Object) : void
      {
         super.OnControlMapChanged(param1);
         if(this.KeyHelper != null)
         {
            this.KeyHelper.OnControlMapChanged(param1);
         }
         this.PopulateButtonBar();
         if(uiController == PlatformUtils.PLATFORM_PC_KB_MOUSE)
         {
            this.TabbedFilterSelection_mc.LeftButton.y = this.startingTabButtonYPosition + KEYBOARD_TAB_BUTTON_OFFSET;
            this.TabbedFilterSelection_mc.RightButton.y = this.startingTabButtonYPosition + KEYBOARD_TAB_BUTTON_OFFSET;
            this.TabbedFilterSelection_mc.UpdateButtonUserEvents(["Left"],["Right"]);
         }
         else
         {
            this.TabbedFilterSelection_mc.LeftButton.y = this.startingTabButtonYPosition;
            this.TabbedFilterSelection_mc.RightButton.y = this.startingTabButtonYPosition;
            this.TabbedFilterSelection_mc.UpdateButtonUserEvents(["LShoulder","Left"],["RShoulder","Right"]);
         }
      }
      
      private function OnCancelEvent() : void
      {
         this.CloseMenu(false);
      }
      
      private function onCloseSubMenuToGame() : *
      {
         this.CloseMenu(true);
      }
      
      private function CloseMenu(param1:Boolean) : *
      {
         if(!this.bClosing)
         {
            this.bClosing = true;
            this.bReturningToGame = param1;
            if(param1)
            {
               GlobalFunc.StartGameRender();
               BSUIDataManager.dispatchEvent(new Event("DataMenu_SetMenuForQuickEntry"));
            }
            gotoAndPlay("Close");
         }
      }
      
      private function OnTimelineCloseEvent() : void
      {
         this.SaveMissionMenuState();
         GlobalFunc.PlayMenuSound("UIMenuMissionsMenuExit");
         if(this.bReturningToGame)
         {
            GlobalFunc.CloseAllMenus();
         }
         else
         {
            GlobalFunc.CloseMenu("BSMissionMenu");
         }
      }
      
      private function OnShowOnMapEvent() : void
      {
         if(MissionsListEntry.IsMission(this.MissionsList_mc.selectedEntry))
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(SHOW_ITEM_LOCATION_EVENT,{
               "questID":this.MissionsList_mc.selectedEntry.uID,
               "objectiveID":-1
            }));
         }
         else
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(SHOW_ITEM_LOCATION_EVENT,{
               "questID":this.MissionsList_mc.selectedEntry.uOwnerQuestFormID,
               "objectiveID":this.MissionsList_mc.selectedEntry.uIndex
            }));
         }
         GlobalFunc.PlayMenuSound(MISSION_SHOW_ON_MAP_SOUND);
      }
      
      private function OnPlotCourseEvent() : void
      {
         // 「可接任务」条目：SET COURSE（键盘 R / 手柄 X）改成我们自己的引导请求，
         // 不把不存在的任务 ID 丢给原版的数据层（那样只会静默失败）。
         if(this.SaqIsOurEntry(this.MissionsList_mc.selectedEntry))
         {
            this.SaqToggleGuide(this.MissionsList_mc.selectedEntry);
            return;
         }
         if(MissionsListEntry.IsMission(this.MissionsList_mc.selectedEntry))
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_PlotToLocation,{
               "questID":this.MissionsList_mc.selectedEntry.uID,
               "objectiveID":-1
            }));
         }
         else
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_PlotToLocation,{
               "questID":this.MissionsList_mc.selectedEntry.uOwnerQuestFormID,
               "objectiveID":this.MissionsList_mc.selectedEntry.uIndex
            }));
         }
         GlobalFunc.PlayMenuSound(MISSION_SHOW_ON_MAP_SOUND);
      }
      
      private function onMissionListItemActivated() : void
      {
         var _loc1_:* = undefined;
         var _loc2_:Boolean = false;
         var _loc3_:Object = null;
         // 「可接任务」条目的 Enter / 鼠标点击 —— 交互与原版对齐（第 14 轮修正）：
         //   · 主标题（有子项）：**不**切换引导 —— 这一步只做「展开/收起」，由
         //     BSScrollingTree.onEntryPress 自己完成（原版点任务主标题也是展开）；
         //   · 子项（「前往接取地点」）：切换引导 —— 对应原版「点目标切换追踪」，
         //     主标题左侧的竖条（TrackIndicator）随之点亮（引导中 = 追踪中的视觉）。
         // 必须在 CanTrackOrUntrack 判定**之前**处理：我们的条目在引擎侧不存在，
         // 落进原版分支会往数据层发一条引擎找不到的任务 ID。
         if(this.SaqIsOurEntry(this.MissionsList_mc.selectedEntry))
         {
            if(!MissionsListEntry.IsMission(this.MissionsList_mc.selectedEntry))
            {
               this.SaqToggleGuide(this.MissionsList_mc.selectedEntry);
            }
            return;
         }
         if(this.CanTrackOrUntrack)
         {
            _loc1_ = this.MissionsList_mc.selectedEntry;
            if(_loc1_ != null)
            {
               this.bSkipSelectionSounds = true;
               this.MissionsList_mc.StoreCurrentListState();
               if(_loc1_.bIsMiscObjective === true)
               {
                  if(_loc1_.bActive)
                  {
                     GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
                  }
                  else
                  {
                     GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
                  }
                  this.scrollPositionAtTracking = this.MissionsList_mc.scrollPosition;
                  this.MissionsList_mc.selectedIndex = -1;
                  BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_ToggleTrackingQuest,{
                     "questID":_loc1_.uOwnerQuestFormID,
                     "instanceID":_loc1_.uInstanceID
                  }));
               }
               else
               {
                  _loc2_ = MissionsListEntry.IsMission(_loc1_);
                  if(_loc2_)
                  {
                     if(_loc1_.bActive)
                     {
                        GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
                     }
                     else
                     {
                        GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
                     }
                     this.scrollPositionAtTracking = this.MissionsList_mc.scrollPosition;
                     BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_ToggleTrackingQuest,{
                        "questID":_loc1_.uID,
                        "instanceID":_loc1_.uInstanceID
                     }));
                  }
                  else
                  {
                     _loc3_ = this.GetParentMissionData(_loc1_);
                     if(_loc3_)
                     {
                        if(_loc3_.bActive)
                        {
                           GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
                        }
                        else
                        {
                           GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
                        }
                        this.scrollPositionAtTracking = this.MissionsList_mc.scrollPosition;
                        BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_ToggleTrackingQuest,{
                           "questID":_loc3_.uID,
                           "instanceID":_loc3_.uInstanceID
                        }));
                     }
                  }
               }
            }
         }
      }
      
      private function OnRejectQuest() : void
      {
         var _loc1_:* = undefined;
         if(this.canReject)
         {
            _loc1_ = this.MissionsList_mc.selectedEntry;
            if(_loc1_ != null)
            {
               GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
               this.MissionsList_mc.StoreCurrentListState();
               this.bSkipSelectionSounds = true;
               if(_loc1_.bIsMiscObjective === true)
               {
                  BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_RejectQuest,{
                     "questID":_loc1_.uOwnerQuestFormID,
                     "instanceID":_loc1_.uInstanceID
                  }));
               }
               else
               {
                  BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_RejectQuest,{
                     "questID":_loc1_.uID,
                     "instanceID":_loc1_.uInstanceID
                  }));
               }
            }
         }
      }
      
      private function onShowButtonBar() : *
      {
         this.ButtonBar_mc.visible = true;
      }
      
      private function SaveMissionMenuState() : *
      {
         var _loc2_:uint = 0;
         BSUIDataManager.dispatchEvent(new Event(MissionMenu_ClearState));
         BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_SaveCategoryIndex,{"uValue":this.TabbedFilterSelection_mc.selectedIndex}));
         var _loc1_:Array = this.MissionsList_mc.GetListOfExpandedQuestIds();
         for each(_loc2_ in _loc1_)
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_SaveOpenedId,{"uValue":_loc2_}));
         }
      }
      
      private function InitializeLastState() : *
      {
         if(!this.InitializedOpenedIds)
         {
            if(this.QuestData != null && this.QuestData.length > 0)
            {
               if(this.StoredLastOpenedIds != null && this.StoredLastOpenedIds.length > 0)
               {
                  this.InitializedOpenedIds = true;
                  this.TabbedFilterSelection_mc.SetSelectedCategoryIndex(this.StoredLastCategory);
                  if(!this.MissionsList_mc.RestorePreviousMissionMenuState(this.StoredLastOpenedIds) && this.TabbedFilterSelection_mc.selectedIndex != 0)
                  {
                     this.TabbedFilterSelection_mc.SetSelectedCategoryIndex(0);
                  }
               }
            }
         }
      }
      
      internal function frame9() : *
      {
         stop();
      }
      
      internal function frame17() : *
      {
         dispatchEvent(new Event("TimelineCloseEvent"));
         stop();
      }
   }
}

