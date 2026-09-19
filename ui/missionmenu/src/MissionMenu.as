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
         while(_loc5_ < param1.length)
         {
            if(!_loc2_[param1[_loc5_].uID])
            {
               _loc4_.push(param1[_loc5_]);
            }
            _loc5_++;
         }
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
      
      private function SaqBuildEntry(param1:Object) : Object
      {
         return {
            "uID":param1.uID,
            "uInstanceID":0,
            "iType":SaqSafeType(param1.iType),
            "iFaction":FactionUtils.FACTION_NONE,
            "sName":this.SaqUseChinese() ? param1.sNameZh : param1.sNameEn,
            "sDescription":"",
            "bActive":false,
            "bComplete":false,
            "bFailed":false,
            "bCanBeRejected":false,
            "bIsMiscQuest":false,
            "bIsMiscObjective":false,
            "bCanShowOnMap":false,
            "iRemainingTime":-1,
            "aObjectives":new Array(),
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
         this.SaqApplyTabTitle();
         if(this.MissionsList_mc != null)
         {
            // 把列表掩码与本菜单当前选中的 tab 对齐一次。
            // （BSScrollingTree 的默认掩码是 0xFFFFFFFF；如果这一帧还没人设置过它，
            //   「全部」tab 会用 0xFFFFFFFF 放行 bSaqAvailable 条目的判据 —— 这里先对齐，
            //   保证重建列表时用的是当前 tab 的真实掩码。）
            this.SaqSyncListMask();
            this.MissionsList_mc.InitializeEntries(this.BuildMergedList());
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
      public function SAQ_Report() : String
      {
         var _loc1_:int = this.SaqRawQuests != null ? this.SaqRawQuests.length : -1;
         var _loc2_:int = this.AvailableQuests != null ? this.AvailableQuests.length : -1;
         var _loc3_:int = this.QuestData != null ? this.QuestData.length : -1;
         var _loc4_:int = this.MissionsList_mc != null ? int(this.MissionsList_mc.entryCount) : -1;
         var _loc5_:int = this.MissionsList_mc != null ? int(this.MissionsList_mc.filterMask) : -1;
         var _loc6_:int = this.TabbedFilterSelection_mc != null ? int(this.TabbedFilterSelection_mc.selectedIndex) : -1;
         var _loc7_:String = this.SaqLangKnown ? (this.SaqLangZh ? "zh" : "en") : "?";
         var _loc8_:String = "src=" + (this.SaqSourceIsCpp ? "cpp" : "embedded")
            + " raw=" + _loc1_
            + " keep=" + _loc2_
            + " questData=" + _loc3_
            + " list=" + _loc4_
            + " mask=0x" + _loc5_.toString(16);
         _loc8_ += " tab=" + _loc6_
            + " lang=" + _loc7_
            + " title=" + this.SaqTabTitle()
            + " visible=" + (this.visible ? "1" : "0");
         return _loc8_;
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
      
      private function GetParentMissionData(param1:Object) : Object
      {
         var _loc3_:uint = 0;
         var _loc2_:* = null;
         if(param1)
         {
            if(MissionsListEntry.IsMission(param1))
            {
               _loc2_ = param1;
            }
            else if(param1.bIsMiscObjective == null || param1.bIsMiscObjective === false)
            {
               _loc3_ = 0;
               while(_loc3_ < this.QuestData.length)
               {
                  if(this.QuestData[_loc3_].uID == param1.uOwnerQuestFormID)
                  {
                     _loc2_ = this.QuestData[_loc3_];
                     break;
                  }
                  _loc3_++;
               }
            }
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

