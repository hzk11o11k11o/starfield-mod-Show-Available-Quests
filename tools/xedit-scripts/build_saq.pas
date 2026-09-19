unit SAQ_BuildPlugin;

// ===========================================================================
//  Starfield Show Available Quests - plugin builder (headless xEdit script)
// ===========================================================================
//
//  !!! THIS FILE MUST STAY PURE ASCII AND MUST NOT CONTAIN ANY BRACE CHARACTER !!!
//  (same two traps as the reference project: xEdit reads .pas as ANSI, and a
//   brace inside a comment truncates it -> parser errors)
//
//  Run:  tools\run-xedit-build.ps1
//
// ---------------------------------------------------------------------------
//  Record table. Creation order == FormID order (low 24 bits).
//
//    0x800  QUST  SAQ_MainQuest       Start Game Enabled + Starts Enabled,
//                                     VMAD -> SAQ_Main.psc
//    0x801  GLOB  SAQ_GuideTargetRef  DLL writes the FormID of the guide
//                                     target (0 = clear). float type.
//    0x802  GLOB  SAQ_GuideState      script -> DLL diagnostic channel
//                                     (0 idle, 1 ok, 2 target not found)
//    0x803  GLOB  SAQ_Notify          HUD notification flag (script reads,
//                                     then zeroes it)
//
//  New records MUST be appended at the END so the earlier FormIDs never move
//  (form ids are archived in save games).
// ---------------------------------------------------------------------------

const
  OutDir     = 'D:\workspace\starfield mod\Show Available Quests\ref\xedit-out\';
  PluginName = 'SAQ_ShowAvailableQuests.esm';
  ScriptMain = 'SAQ_Main';

var
  sl: TStringList;
  srcFile: IwbFile;
  questRec: IInterface;
  globTarget, globState, globNotify: IInterface;

procedure Log(s: string);
begin
  sl.Add(s);
end;

procedure Flush(tag: string);
begin
  sl.SaveToFile(OutDir + 'h_' + tag + '.txt');
end;

function TopGroup(f: IwbFile; sig: string): IInterface;
var
  i: Integer;
  g: IInterface;
begin
  Result := nil;
  for i := 0 to Pred(ElementCount(f)) do begin
    g := ElementByIndex(f, i);
    if Name(g) = 'GRUP Top "' + sig + '"' then begin
      Result := g;
      Exit;
    end;
  end;
end;

function FindByEdid(f: IwbFile; sig, edid: string): IInterface;
var
  g, r: IInterface;
  i: Integer;
begin
  Result := nil;
  g := TopGroup(f, sig);
  if not Assigned(g) then Exit;
  for i := 0 to Pred(ElementCount(g)) do begin
    r := ElementByIndex(g, i);
    if GetElementEditValues(r, 'EDID') = edid then begin
      Result := r;
      Exit;
    end;
  end;
end;

function FindFloatGlobalTemplate(): IInterface;
var
  g, r: IInterface;
  i: Integer;
begin
  Result := nil;
  g := TopGroup(srcFile, 'GLOB');
  if not Assigned(g) then begin
    Log('ERR: no GLOB group');
    Exit;
  end;
  for i := 0 to Pred(ElementCount(g)) do begin
    r := ElementByIndex(g, i);
    if not Assigned(ElementBySignature(r, 'EDID')) then Continue;
    Result := r;
    Exit;
  end;
end;

function MakeGlobal(newFile: IwbFile; edid: string; tpl: IInterface; value: Double): IInterface;
var
  rec: IInterface;
begin
  Result := nil;
  if not Assigned(tpl) then begin
    Log('ERR: GLOB template missing');
    Exit;
  end;
  AddRequiredElementMasters(tpl, newFile, False);
  rec := wbCopyElementToFile(tpl, newFile, True, True);
  if not Assigned(rec) then begin
    Log('ERR: GLOB copy failed ' + edid);
    Exit;
  end;
  SetElementEditValues(rec, 'EDID', edid);
  SetElementNativeValues(rec, 'FNAM', 2);
  SetElementNativeValues(rec, 'FLTV', value);
  Log('GLOB ok: ' + edid + ' FLTV=' + GetElementEditValues(rec, 'FLTV')
    + ' ' + IntToHex(GetLoadOrderFormID(rec), 8));
  Result := rec;
end;

function MakeQuestSkeleton(newFile: IwbFile; edid, sname: string): IInterface;
var
  tpl, rec, vmad, scripts, scriptRec: IInterface;
begin
  Result := nil;
  tpl := FindByEdid(srcFile, 'QUST', 'SQ_PlayerHouse');
  if not Assigned(tpl) then begin
    Log('ERR: QUST template SQ_PlayerHouse missing');
    Exit;
  end;
  AddRequiredElementMasters(tpl, newFile, False);
  rec := wbCopyElementToFile(tpl, newFile, True, True);
  if not Assigned(rec) then begin
    Log('ERR: QUST copy failed');
    Exit;
  end;
  SetElementEditValues(rec, 'EDID', edid);

  // Start Game Enabled (0x01) + Starts Enabled (0x10)
  SetElementNativeValues(rec, 'DNAM\Flags', 17);

  if ElementExists(rec, 'VMAD') then
    RemoveElement(rec, 'VMAD');
  vmad := Add(rec, 'VMAD', True);
  SetElementNativeValues(vmad, 'Version', 6);
  SetElementNativeValues(vmad, 'Object Format', 2);

  scripts := ElementByPath(vmad, 'Scripts');
  scriptRec := ElementAssign(scripts, HighInteger, nil, False);
  SetElementEditValues(scriptRec, 'ScriptName', sname);
  SetElementNativeValues(scriptRec, 'Flags', 0);

  Log('QUST ok: ' + edid + ' ' + IntToHex(GetLoadOrderFormID(rec), 8));
  Result := rec;
end;

function AddQuestProp(a_quest: IInterface; pname: string; target: IInterface): Boolean;
var
  vmad, scripts, scriptRec, props, prop: IInterface;
begin
  Result := False;
  if not Assigned(a_quest) then begin
    Log('  ERR AddQuestProp: quest missing (' + pname + ')');
    Exit;
  end;
  if not Assigned(target) then begin
    Log('  ERR AddQuestProp: target missing (' + pname + ')');
    Exit;
  end;
  vmad := ElementByPath(a_quest, 'VMAD');
  if not Assigned(vmad) then begin
    Log('  ERR AddQuestProp: VMAD missing (' + pname + ')');
    Exit;
  end;
  scripts := ElementByPath(vmad, 'Scripts');
  if not Assigned(scripts) then begin
    Log('  ERR AddQuestProp: Scripts missing (' + pname + ')');
    Exit;
  end;
  scriptRec := ElementByIndex(scripts, 0);
  if not Assigned(scriptRec) then begin
    Log('  ERR AddQuestProp: script record missing');
    Exit;
  end;
  props := ElementByPath(scriptRec, 'Properties');
  if not Assigned(props) then
    props := Add(scriptRec, 'Properties', True);
  prop := ElementAssign(props, HighInteger, nil, False);
  SetElementEditValues(prop, 'propertyName', pname);
  SetElementNativeValues(prop, 'Type', 1);
  SetElementNativeValues(prop, 'Flags', 1);
  SetElementEditValues(prop, 'Value\Object Union\Object v2\FormID', Name(target));
  Log('  prop ' + pname + ' -> ' + Name(target));
  Result := True;
end;

function DoBuild: Integer;
var
  newFile: IwbFile;
  globTpl: IInterface;
  fs: TFileStream;
  i: Integer;
begin
  sl := TStringList.Create;
  Log('=== Show Available Quests build start ===');
  Flush('00_start');

  srcFile := FileByIndex(0);
  Log('src = ' + GetFileName(srcFile));

  newFile := AddNewFileName(PluginName);
  if not Assigned(newFile) then begin
    Log('FATAL: cannot create ' + PluginName);
    Flush('99_fatal');
    sl.Free;
    Result := 1;
    Exit;
  end;
  SetIsESM(newFile, True);
  Log('plugin created');
  Flush('01_created');

  globTpl := FindFloatGlobalTemplate();
  Flush('02_globtpl');

  // ------- 0x800 -------
  questRec := MakeQuestSkeleton(newFile, 'SAQ_MainQuest', ScriptMain);
  Flush('03_quest');

  // ------- 0x801 / 0x802 / 0x803 -------
  globTarget := MakeGlobal(newFile, 'SAQ_GuideTargetRef', globTpl, 0.0);
  globState  := MakeGlobal(newFile, 'SAQ_GuideState', globTpl, 0.0);
  globNotify := MakeGlobal(newFile, 'SAQ_Notify', globTpl, 0.0);
  Flush('04_globals');

  // VMAD properties (added after all target records exist)
  AddQuestProp(questRec, 'GuideTargetRef', globTarget);
  AddQuestProp(questRec, 'GuideState', globState);
  AddQuestProp(questRec, 'NotifyFlag', globNotify);
  Flush('05_vmad');

  try
    SortMasters(newFile);
    Log('masters:');
    for i := 0 to Pred(MasterCount(newFile)) do
      Log('  ' + GetFileName(MasterByIndex(newFile, i)));
  except
    on E: Exception do Log('EXC sort: ' + E.Message);
  end;

  try
    fs := TFileStream.Create(OutDir + PluginName, fmCreate);
    try
      FileWriteToStream(newFile, fs, False);
    finally
      fs.Free;
    end;
    Log('saved: ' + OutDir + PluginName);
  except
    on E: Exception do Log('EXC save: ' + E.Message);
  end;

  Log('--- FormID map (low 24 bits) ---');
  Log('  0x800 SAQ_MainQuest       ' + IntToHex(GetLoadOrderFormID(questRec) and $FFFFFF, 6));
  Log('  0x801 SAQ_GuideTargetRef  ' + IntToHex(GetLoadOrderFormID(globTarget) and $FFFFFF, 6));
  Log('  0x802 SAQ_GuideState      ' + IntToHex(GetLoadOrderFormID(globState) and $FFFFFF, 6));
  Log('  0x803 SAQ_Notify          ' + IntToHex(GetLoadOrderFormID(globNotify) and $FFFFFF, 6));

  Log('=== build done ===');
  Flush('99_done');
  sl.Free;
  Result := 0;
end;

function Initialize: Integer;
begin
  try
    Result := DoBuild;
  except
    on E: Exception do begin
      try
        if Assigned(sl) then begin
          Log('EXCEPTION: ' + E.Message);
          Flush('98_exception');
          sl.Free;
        end;
      except
      end;
      Result := 1;
    end;
  end;
end;

end.
