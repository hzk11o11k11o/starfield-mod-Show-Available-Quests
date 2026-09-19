package
{
   import Shared.AS3.BSTabbedSelectionEntry;
   import flash.display.MovieClip;
   
   [Embed(source="/_assets/assets.swf", symbol="symbol42")]
   public class CategoryTab extends BSTabbedSelectionEntry
   {
      
      public var Highlight_mc:MovieClip;
      
      public var Border_mc:MovieClip;
      
      public function CategoryTab()
      {
         super();
         addFrameScript(0,this.frame1,1,this.frame2);
      }
      
      override protected function UpdateBaseData(param1:String, param2:Boolean, param3:String) : *
      {
         super.UpdateBaseData(param1,param2,param3);
         this.Highlight_mc.visible = param2;
      }
      
      internal function frame1() : *
      {
         stop();
      }
      
      internal function frame2() : *
      {
         stop();
      }
   }
}

