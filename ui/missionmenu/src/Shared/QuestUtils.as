package Shared
{
   import flash.display.MovieClip;
   
   public class QuestUtils
   {
      
      public static const ACTIVITY_QUEST_TYPE:* = EnumHelper.GetEnum(0);
      
      public static const MAIN_QUEST_TYPE:* = EnumHelper.GetEnum();
      
      public static const FACTION_QUEST_TYPE:* = EnumHelper.GetEnum();
      
      public static const MISC_QUEST_TYPE:* = EnumHelper.GetEnum();
      
      public static const MISSION_QUEST_TYPE:* = EnumHelper.GetEnum();
      
      public static const COMPLETED_QUEST_TYPE:* = EnumHelper.GetEnum();
      
      public static const AVAILABLE_QUEST_TYPE:* = 6;
      
      public function QuestUtils()
      {
         super();
      }
      
      public static function GetQuestIconLabel(param1:int, param2:int) : String
      {
         if(param2 == ACTIVITY_QUEST_TYPE)
         {
            return "Activities";
         }
         if(param1 != FactionUtils.FACTION_NONE)
         {
            return FactionUtils.GetFactionIconLabel(param1);
         }
         switch(param2)
         {
            case MISC_QUEST_TYPE:
               return "Misc";
            case MISSION_QUEST_TYPE:
               return "Missions";
            default:
               return "None";
         }
      }
      
      public static function ShowFactionIcon(param1:int, param2:int, param3:String, param4:MovieClip, param5:MovieClip, param6:Boolean = false) : *
      {
         if(!param4)
         {
            return;
         }
         if(!param3 || param3 == "")
         {
            param4.gotoAndStop(GetQuestIconLabel(param1,param2) + (param6 ? "Large" : ""));
         }
         else
         {
            param4.gotoAndStop(GetQuestIconLabel(param1,param2) + (param6 ? "Large" : ""));
            if(param5)
            {
               param5.LoadSymbol(param3,param3);
            }
         }
      }
   }
}

