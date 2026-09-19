package
{
   import Components.BSButton;
   
   [Embed(source="/_assets/assets.swf", symbol="symbol5")]
   public dynamic class ObjectiveButton extends BSButton
   {
      
      public function ObjectiveButton()
      {
         super();
         addFrameScript(0,this.frame1,1,this.frame2,3,this.frame4,5,this.frame6,6,this.frame7,7,this.frame8,8,this.frame9,10,this.frame11,12,this.frame13,14,this.frame15,15,this.frame16,16,this.frame17);
      }
      
      internal function frame1() : *
      {
         stop();
      }
      
      internal function frame2() : *
      {
         gotoAndPlay("idle");
      }
      
      internal function frame4() : *
      {
         gotoAndPlay("over");
      }
      
      internal function frame6() : *
      {
         stop();
      }
      
      internal function frame7() : *
      {
         gotoAndPlay("over");
      }
      
      internal function frame8() : *
      {
         stop();
      }
      
      internal function frame9() : *
      {
         gotoAndStop("down");
      }
      
      internal function frame11() : *
      {
         gotoAndStop("down");
      }
      
      internal function frame13() : *
      {
         gotoAndStop("idle");
      }
      
      internal function frame15() : *
      {
         stop();
      }
      
      internal function frame16() : *
      {
         stop();
      }
      
      internal function frame17() : *
      {
         stop();
      }
   }
}

