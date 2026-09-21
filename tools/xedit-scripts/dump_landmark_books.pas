unit DumpLandmarkBooks;

// ===========================================================================
//  Show Available Quests - 「地标书」完整 VMAD 导出
// ===========================================================================
//
//  !!! 必须纯 ASCII，且不能出现花括号字符 !!!
//
//  条件：BOOK / NOTE 记录满足其一
//    1) VMAD 脚本含 'defaultrefoncontainerchangedto'（拾取触发脚本）
//    2) EDID 含 'RL089'（Opportunity 数据板候选）
//    3) EDID 含 'Landmark'
//  输出全树（depth 12）到 ref\xedit\landmark_books.txt
// ===========================================================================

const
  OutDir = 'd:\workspace\starfield mod\Show Available Quests\ref\xedit\';

var
  sl: TStringList;

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

procedure DumpTree(e: IInterface; indent: string; depth: Integer);
var
  i, n: Integer;
  nm, val, sig: string;
begin
  if depth > 12 then Exit;
  sig := Signature(e);
  nm := Name(e);
  if Pos('Data Bytes', nm) > 0 then Exit;
  n := ElementCount(e);
  if n = 0 then begin
    val := GetEditValue(e);
    if val = '' then val := GetNativeValue(e);
    if Length(val) > 260 then val := Copy(val, 1, 260) + ' ...';
    sl.Add(indent + nm + ' = ' + val);
  end else begin
    sl.Add(indent + nm + ' [' + sig + '] (' + IntToStr(n) + ')');
    for i := 0 to Pred(n) do
      DumpTree(ElementByIndex(e, i), indent + '  ', depth + 1);
  end;
end;

procedure ScanGroup(f: IInterface; sig: string);
var
  g, r: IInterface;
  i: Integer;
  edid, sc: string;
  hit: Boolean;
begin
  g := GroupBySignature(f, sig);
  if not Assigned(g) then begin
    sl.Add('## ' + sig + ' absent');
    Exit;
  end;
  for i := 0 to Pred(ElementCount(g)) do begin
    r := ElementByIndex(g, i);
    if Signature(r) <> sig then Continue;
    edid := GetElementEditValues(r, 'EDID');
    sc := VmadScripts(r);
    hit := False;
    if Pos('defaultrefoncontainerchangedto', LowerCase(sc)) > 0 then hit := True;
    if Pos('rl089', LowerCase(edid)) > 0 then hit := True;
    if Pos('landmark', LowerCase(edid)) > 0 then hit := True;
    if hit then begin
      sl.Add('');
      sl.Add('==== ' + sig + ' ' + IntToHex(GetLoadOrderFormID(r), 8) + ' ' + edid + '  scripts=' + sc + ' ====');
      DumpTree(r, '', 0);
    end;
  end;
end;

function Initialize: Integer;
var
  f: IInterface;
begin
  sl := TStringList.Create;
  sl.Add('=== landmark books dump begin ===');
  f := FileByIndex(0);
  ScanGroup(f, 'BOOK');
  ScanGroup(f, 'NOTE');
  sl.Add('');
  sl.Add('=== end ===');
  sl.SaveToFile(OutDir + 'landmark_books.txt');
  sl.Free;
  Result := 0;
end;

end.
