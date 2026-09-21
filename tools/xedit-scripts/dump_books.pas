unit DumpBooks;

// ===========================================================================
//  Show Available Quests - BOOK / NOTE 索引导出 + 含 landmark 的记录全树
// ===========================================================================
//
//  !!! 必须纯 ASCII，且不能出现花括号字符 !!!
//  （xEdit 按 ANSI 读 .pas；花括号注释会在第一个右花括号处提前结束）
//
//  输出（ref\xedit\）：
//    books_index.txt   BOOK + NOTE 索引：FormID|EDID|FULL|VMAD 脚本名
//    books_detail.txt  名称含 landmark / snowglobe 的 BOOK/NOTE/MISC 全树
//
//  用途：查证「地球地标」系列任务（Landmark_*）的触发方式 ——
//        找到对应书籍记录与它的脚本 / 任务关联。
//
//  用法（由 tools/run-xedit.ps1 调用）：
//    xSFEdit64.exe -SF1 -script:dump_books.pas -D:<Data> -P:plugins.txt
// ===========================================================================

const
  OutDir = 'd:\workspace\starfield mod\Show Available Quests\ref\xedit\';

var
  sl: TStringList;
  sl2: TStringList;

function VmadScripts(r: IInterface): string;
var
  v, scripts, s: IInterface;
  i: Integer;
  nm: string;
begin
  Result := '';
  v := ElementByPath(r, 'VMAD');
  if not Assigned(v) then Exit;
  scripts := ElementByPath(v, 'Scripts');
  if not Assigned(scripts) then Exit;
  for i := 0 to Pred(ElementCount(scripts)) do begin
    s := ElementByIndex(scripts, i);
    nm := GetElementEditValues(s, 'scriptName');
    if nm = '' then nm := GetElementEditValues(s, 'ScriptName');
    if Result <> '' then Result := Result + ',';
    Result := Result + nm;
  end;
end;

procedure DumpIndex(f: IInterface; sig: string);
var
  g, r: IInterface;
  i: Integer;
  edid, full, sc: string;
begin
  g := GroupBySignature(f, sig);
  if not Assigned(g) then begin
    sl.Add('## ' + sig + ' absent');
    Exit;
  end;
  sl.Add('## ' + sig + ' count=' + IntToStr(ElementCount(g)));
  for i := 0 to Pred(ElementCount(g)) do begin
    r := ElementByIndex(g, i);
    if Signature(r) <> sig then Continue;
    edid := GetElementEditValues(r, 'EDID');
    full := GetElementEditValues(r, 'FULL');
    if Length(full) > 120 then full := Copy(full, 1, 120);
    sc := VmadScripts(r);
    sl.Add(IntToHex(GetLoadOrderFormID(r), 8) + '|' + edid + '|' + full + '|' + sc);
  end;
end;

procedure DumpTree(e: IInterface; indent: string; depth: Integer);
var
  i, n: Integer;
  nm, val, sig: string;
begin
  if depth > 8 then Exit;
  sig := Signature(e);
  nm := Name(e);
  if Pos('Data', nm) > 0 then Exit;
  n := ElementCount(e);
  if n = 0 then begin
    val := GetEditValue(e);
    if val = '' then val := GetNativeValue(e);
    if Length(val) > 200 then val := Copy(val, 1, 200) + ' ...';
    sl2.Add(indent + nm + ' = ' + val);
  end else begin
    sl2.Add(indent + nm + ' [' + sig + '] (' + IntToStr(n) + ')');
    for i := 0 to Pred(n) do
      DumpTree(ElementByIndex(e, i), indent + '  ', depth + 1);
  end;
end;

procedure DumpDetail(f: IInterface; sig, substr: string);
var
  g, r: IInterface;
  i: Integer;
  edid: string;
begin
  g := GroupBySignature(f, sig);
  if not Assigned(g) then Exit;
  for i := 0 to Pred(ElementCount(g)) do begin
    r := ElementByIndex(g, i);
    if Signature(r) <> sig then Continue;
    edid := GetElementEditValues(r, 'EDID');
    if Pos(LowerCase(substr), LowerCase(edid)) > 0 then begin
      sl2.Add('');
      sl2.Add('==== ' + sig + ' ' + IntToHex(GetLoadOrderFormID(r), 8) + ' ' + edid + ' ====');
      DumpTree(r, '', 0);
    end;
  end;
end;

function Initialize: Integer;
var
  f: IInterface;
begin
  sl := TStringList.Create;
  sl2 := TStringList.Create;
  sl2.Add('=== detail dump begin ===');
  f := FileByIndex(0);
  DumpIndex(f, 'BOOK');
  DumpIndex(f, 'NOTE');
  DumpDetail(f, 'BOOK', 'landmark');
  DumpDetail(f, 'NOTE', 'landmark');
  DumpDetail(f, 'MISC', 'snowglobe');
  DumpDetail(f, 'MISC', 'landmark');
  sl2.Add('');
  sl2.Add('=== detail dump end ===');
  sl.SaveToFile(OutDir + 'books_index.txt');
  sl2.SaveToFile(OutDir + 'books_detail.txt');
  sl.Free;
  sl2.Free;
  Result := 0;
end;

end.
