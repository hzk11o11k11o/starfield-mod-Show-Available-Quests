unit SAQ_VerifyPersist;

// ===========================================================================
//  Show Available Quests - 校验「任务板常驻 marker」（无头 xEdit 脚本）
// ===========================================================================
//
//  !!! 必须纯 ASCII，且不能出现花括号字符 !!!
//  （xEdit 按 ANSI 读 .pas；花括号注释会在第一个右花括号处提前结束）
//
//  背景（第 30 轮）：第 29 轮的「override 成常驻」路线已被实机否定，现在改成在
//  SAQ_ShowAvailableQuests.esm 里**新建** 11 条常驻 XMarker 引用：
//    * EDID = SAQ_BoardMarker_<板记录号>、base = XMarker(0x3B)；
//    * flags = 0x400（Persistent）、组链 = Top 'CELL' > 块 > 子块 > CellChildren > CellPersistent；
//    * 记录头 FormID 的空间索引 = 本文件 MAST 数量（= 2，自身空间）。
//  需要 xEdit 这个社区标准解析器确认：它能不能读懂这棵树、记录是不是本文件自己的
//  （而不是误认成覆盖别的 master）。
//
//  做两件事：
//    1. 把 SAQ_ShowAvailableQuests.esm 的 CELL 组树 dump 到 verify_persist.txt
//       （组名 + 每条记录的 sig/FormID/flags/EDID，EDID 前缀命中的标 <<< marker）；
//    2. 让 xEdit 把该文件**原样重新保存**成 SAQ_resaved.esm —— 如果 xEdit 真读懂了
//       这些新记录，重存文件里它们仍在（且仍在 Cell Persistent 组）；读不懂就会丢。
//
//  运行：tools\run-verify-persist.ps1
// ===========================================================================

const
  OutDir     = 'd:\workspace\starfield mod\Show Available Quests\ref\xedit-out\';
  TargetFile = 'SAQ_ShowAvailableQuests.esm';

var
  sl: TStringList;

function FindTarget(): IInterface;
var
  i: Integer;
  f: IInterface;
begin
  Result := nil;
  for i := 0 to Pred(FileCount) do begin
    f := FileByIndex(i);
    if SameText(GetFileName(f), TargetFile) then begin
      Result := f;
      Exit;
    end;
  end;
end;

function TopGroup(f: IInterface; sig: string): IInterface;
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

procedure Walk(e: IInterface; depth: Integer; var hits: Integer; var cells: Integer);
var
  i: Integer;
  c: IInterface;
  nm, sig, line, edid: string;
begin
  for i := 0 to Pred(ElementCount(e)) do begin
    c := ElementByIndex(e, i);
    nm := Name(c);
    if Copy(nm, 1, 4) = 'GRUP' then begin
      sl.Add(StringOfChar(' ', depth * 2) + nm);
      Walk(c, depth + 1, hits, cells);
    end else begin
      sig := Signature(c);
      line := StringOfChar(' ', depth * 2) + sig + ' ' + IntToHex(GetLoadOrderFormID(c), 8);
      try
        line := line + ' flags=[' + GetElementEditValues(c, 'Record Header\Record Flags') + ']';
      except
        line := line + ' flags[exception]';
      end;
      edid := '';
      try
        edid := GetElementEditValues(c, 'EDID');
      except
      end;
      if edid <> '' then
        line := line + ' EDID=' + edid;
      if Copy(edid, 1, 16) = 'SAQ_BoardMarker_' then begin
        line := line + '   <<< marker';
        Inc(hits);
      end;
      (* round 33: CELL record override (byte copy of Starfield.esm) --
         the engine merges our CellChildren group only when the plugin also
         writes that CELL record, so each marker must come with one. *)
      if sig = 'CELL' then begin
        line := line + '   <<< CELL override (round 33, host cell of a marker)';
        Inc(cells);
      end;
      sl.Add(line);
    end;
  end;
end;

function Initialize: Integer;
var
  f, g: IInterface;
  fs: TFileStream;
  i, hits, cells: Integer;
begin
  sl := TStringList.Create;
  sl.Add('=== SAQ verify markers begin ===');
  sl.Add('files in load order:');
  for i := 0 to Pred(FileCount) do
    sl.Add('  [' + IntToStr(i) + '] ' + GetFileName(FileByIndex(i)));

  f := FindTarget();
  if not Assigned(f) then begin
    sl.Add('FATAL: could not find ' + TargetFile);
    sl.SaveToFile(OutDir + 'verify_persist.txt');
    sl.Free;
    Result := 1;
    Exit;
  end;

  sl.Add('');
  sl.Add('=== ' + TargetFile + ' cell group tree ===');
  g := TopGroup(f, 'CELL');
  hits := 0;
  cells := 0;
  if not Assigned(g) then begin
    sl.Add('NO GRUP Top "CELL" -- markers missing?');
  end else begin
    Walk(g, 0, hits, cells);
  end;
  sl.Add('marker hits = ' + IntToStr(hits) + ' (expect 11)');
  sl.Add('CELL overrides = ' + IntToStr(cells) + ' (expect 11, round 33)');
  sl.Add('note: FormID here is xEdit load-order formid; a NEW record of this file shows');
  sl.Add('      with the file own prefix and 0x900+i low bits, NOT as 00xxxxxx override.');
  sl.Add('      The CELL records MUST show as master-space 00xxxxxx (override of Starfield.esm).');

  try
    fs := TFileStream.Create(OutDir + 'SAQ_resaved.esm', fmCreate);
    try
      FileWriteToStream(f, fs, False);
      sl.Add('resaved: ' + OutDir + 'SAQ_resaved.esm');
    finally
      fs.Free;
    end;
  except
    on E: Exception do sl.Add('EXC resave: ' + E.Message);
  end;

  sl.Add('=== done ===');
  sl.SaveToFile(OutDir + 'verify_persist.txt');
  sl.Free;
  // 让 run-xedit.ps1 立刻收尾
  sl := TStringList.Create;
  sl.Add('done');
  sl.SaveToFile(OutDir + 'v_done.txt');
  sl.Free;
  Result := 0;
end;

end.
