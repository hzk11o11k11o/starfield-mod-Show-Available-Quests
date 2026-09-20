unit SAQ_VerifyPersist;

// ===========================================================================
//  Show Available Quests - 校验「任务板入口常驻化」override（无头 xEdit 脚本）
// ===========================================================================
//
//  !!! 必须纯 ASCII，且不能出现花括号字符 !!!
//  （xEdit 按 ANSI 读 .pas；花括号注释会在第一个右花括号处提前结束）
//
//  背景：第 29 轮把 11 条非常驻任务板引用在 SAQ_ShowAvailableQuests.esm 里写成
//  override（flags |= 0x400，放进 CellPersistent 组）—— 需要 xEdit 这个社区标准
//  解析器确认：它能不能读懂这棵树、认出来的 FormID 是不是 Starfield.esm 的记录。
//
//  做两件事：
//    1. 把 SAQ_ShowAvailableQuests.esm 的 CELL 组树 dump 到 verify_persist.txt
//       （组名 + 每条记录的 sig/FormID/flags 文本）；
//    2. 让 xEdit 把该文件**原样重新保存**成 SAQ_resaved.esm —— 如果 xEdit 真读懂了
//       override，重存文件里这些记录仍在（且仍在 Persistent 组）；读不懂就会丢。
//
//  运行：tools\run-verify-persist.ps1
// ===========================================================================

const
  OutDir     = 'd:\workspace\starfield mod\Show Available Quests\ref\xedit-out\';
  TargetFile = 'SAQ_ShowAvailableQuests.esm';

var
  sl: TStringList;
  wanted: array[0..10] of Cardinal;

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

function IsWanted(fid: Cardinal): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := Low(wanted) to High(wanted) do
    if wanted[i] = fid then begin
      Result := True;
      Exit;
    end;
end;

procedure Walk(e: IInterface; depth: Integer);
var
  i: Integer;
  c: IInterface;
  nm, sig, line: string;
begin
  for i := 0 to Pred(ElementCount(e)) do begin
    c := ElementByIndex(e, i);
    nm := Name(c);
    if Copy(nm, 1, 4) = 'GRUP' then begin
      sl.Add(StringOfChar(' ', depth * 2) + nm);
      Walk(c, depth + 1);
    end else begin
      sig := Signature(c);
      line := StringOfChar(' ', depth * 2) + sig + ' ' + IntToHex(GetLoadOrderFormID(c), 8);
      try
        line := line + ' flags=[' + GetElementEditValues(c, 'Record Header\Record Flags') + ']';
      except
        line := line + ' flags[exception]';
      end;
      if IsWanted(GetLoadOrderFormID(c) and $FFFFFF) then
        line := line + '   <<< 目标';
      sl.Add(line);
    end;
  end;
end;

function Initialize: Integer;
var
  f, g: IInterface;
  fs: TFileStream;
  i, n: Integer;
begin
  sl := TStringList.Create;
  sl.Add('=== SAQ verify persist begin ===');
  sl.Add('files in load order:');

  wanted[0] := $0021001E;   // 新亚特兰蒂斯城
  wanted[1] := $00148C93;   // 霓虹城
  wanted[2] := $001DF853;   // 赛多尼亚
  wanted[3] := $001DED95;   // 霍普镇
  wanted[4] := $001DF5BD;   // 新家园
  wanted[5] := $00137573;   // 陋室
  wanted[6] := $0013F738;   // 龙神集团
  wanted[7] := $000C2D64;   // 火卫二造船厂
  wanted[8] := $0016265F;   // 海神叉造船厂
  wanted[9] := $00167872;   // 斯特劳艾克伦集团造船厂
  wanted[10] := $00197D22;  // 星钥站

  for i := 0 to Pred(FileCount) do
    sl.Add('  [' + IntToStr(i) + '] ' + GetFileName(FileByIndex(i)));

  f := FindTarget();
  if not Assigned(f) then begin
    sl.Add('FATAL: 找不到 ' + TargetFile);
    sl.SaveToFile(OutDir + 'verify_persist.txt');
    sl.Free;
    Result := 1;
    Exit;
  end;

  sl.Add('');
  sl.Add('=== ' + TargetFile + ' cells group tree ===');
  g := TopGroup(f, 'CELL');
  if not Assigned(g) then begin
    sl.Add('没有 GRUP Top "CELL"（override 没写进去？）');
    n := 0;
  end else begin
    Walk(g, 0);
    n := 0;
    for i := Low(wanted) to High(wanted) do
      Inc(n);
    sl.Add('（目标记录共 ' + IntToStr(n) + ' 条，上面带 <<< 的是命中的）');
  end;

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
