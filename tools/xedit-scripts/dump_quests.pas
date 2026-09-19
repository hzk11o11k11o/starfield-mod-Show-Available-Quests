unit DumpQuests;

// ===========================================================================
//  Show Available Quests - QUST 全量导出（无头 xEdit 脚本）
// ===========================================================================
//
//  !!! 必须纯 ASCII，且不能出现花括号字符 !!!
//  （xEdit 按 ANSI 读 .pas；花括号注释会在第一个右花括号处提前结束）
//
//  输出：
//    quests_typed.txt  有 QTYP 的任务（玩家可见任务）的关键结构
//    quests_all.txt    全部 QUST 的摘要：FormID|EDID|QTYP
//
//  注意：必须用 GetEditValue()/GetNativeValue() 取叶子值，
//        GetElementEditValues(e, '') 对叶子返回空串。
//
//  用法（由 tools/run-xedit.ps1 调用）：
//    xSFEdit64.exe -SF1 -script:dump_quests.pas -D:<Data> -P:plugins.txt
// ===========================================================================

const
  OutDir = 'd:\workspace\starfield mod\Show Available Quests\ref\xedit\';

var
  sl: TStringList;
  slAll: TStringList;

procedure DumpRecursive(e: IInterface; depth: Integer);
var
  i, n: Integer;
  val, nm, ind: string;
  sig: string;
begin
  if depth > 9 then Exit;
  sig := Signature(e);
  nm := Name(e);
  ind := StringOfChar(' ', depth * 2);
  if (sig = 'VMAD') or (sig = 'Record Header') or (sig = 'MAST') then begin
    sl.Add(ind + sig + ' (skip)');
    Exit;
  end;
  n := ElementCount(e);
  if n = 0 then begin
    val := GetEditValue(e);
    if val = '' then
      val := GetNativeValue(e);
    if Length(val) > 260 then
      val := Copy(val, 1, 260) + ' ...';
    sl.Add(ind + nm + ' = ' + val);
  end else begin
    sl.Add(ind + nm + ' [' + sig + '] (' + IntToStr(n) + ')');
    for i := 0 to Pred(n) do
      DumpRecursive(ElementByIndex(e, i), depth + 1);
  end;
end;

function Initialize: Integer;
var
  f, g, r: IInterface;
  i, typed, total: Integer;
  edid, qtyp: string;
begin
  sl := TStringList.Create;
  slAll := TStringList.Create;
  sl.Add('=== QUST typed dump begin ===');
  slAll.Add('FormID|EDID|QTYP');

  f := FileByIndex(0);
  g := GroupBySignature(f, 'QUST');
  if not Assigned(g) then begin
    sl.Add('QUST group absent!');
    sl.SaveToFile(OutDir + 'quests_typed.txt');
    slAll.SaveToFile(OutDir + 'quests_all.txt');
    Result := 0;
    Exit;
  end;

  total := ElementCount(g);
  typed := 0;
  for i := 0 to Pred(total) do begin
    r := ElementByIndex(g, i);
    edid := GetElementEditValues(r, 'EDID');
    qtyp := GetElementEditValues(r, 'QTYP');
    slAll.Add(Format('%s|%s|%s', [
      IntToHex(GetLoadOrderFormID(r), 8), edid, qtyp]));
    if qtyp <> '' then begin
      Inc(typed);
      sl.Add('');
      sl.Add('=== ' + IntToHex(GetLoadOrderFormID(r), 8) + '  ' + edid + ' ===');
      DumpRecursive(r, 0);
    end;
  end;

  sl.Add('');
  sl.Add('=== total=' + IntToStr(total) + ' typed=' + IntToStr(typed) + ' ===');
  sl.SaveToFile(OutDir + 'quests_typed.txt');
  slAll.SaveToFile(OutDir + 'quests_all.txt');
  sl.Free;
  slAll.Free;
  Result := 0;
end;

end.
