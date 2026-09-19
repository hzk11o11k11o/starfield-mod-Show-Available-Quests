package Shared.Components.ButtonControls.ButtonData
{
   import Shared.GlobalFunc;
   
   public class ButtonData
   {
      
      public var UserEvents:UserEventManager = null;
      
      public var sClickSound:String = "";
      
      public var sClickFailedSound:String = GlobalFunc.CANCEL_SOUND;
      
      public var sRolloverSound:String = GlobalFunc.FOCUS_SOUND;
      
      public var bEnabled:Boolean = true;
      
      public var bVisible:Boolean = true;
      
      public var bUsePCKeyOutline:Boolean = true;
      
      public function ButtonData()
      {
         super();
      }
   }
}

