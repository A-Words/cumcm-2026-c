import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Author only with the Codex-bundled artifact tool. Python is used separately
// for independent, read-only verification of the saved OpenXML workbooks.
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUTPUT = path.join(ROOT, 'outputs/deliverables');
const PREVIEWS = path.join(ROOT, 'tmp', 'workbook-previews');
const BUNDLED_MODULES = process.env.CODEX_BUNDLED_NODE_MODULES
  ?? 'C:/Users/A_Words/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const FILES = [
  ['result1.xlsx', 'q1'], ['result2.xlsx', 'q2'], ['result3.xlsx', 'q3'],
  ['result4-2.xlsx', 'q4_2'], ['result4-3.xlsx', 'q4_3'],
];
const PERIODS = ['0:00-4:00', '4:00-8:00', '8:00-12:00', '12:00-16:00', '16:00-20:00', '20:00-24:00'];
const EPSILON = 1e-7;
const TEMPLATE_EDGE = { style: 'thin', color: '#000000' };
const time = (minute) => `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, '0')}`;
const INTERVALS = Array.from({ length: 144 }, (_, i) => `${time(i * 10)}-${time((i + 1) * 10)}`);
const sum = (values) => values.reduce((total, value) => total + value, 0);
const close = (actual, expected, label) => {
  if (typeof actual !== 'number' || !Number.isFinite(actual)
    || Math.abs(actual - expected) > Math.max(1e-6, Math.abs(expected) * 1e-10)) {
    throw new Error(`${label}: ${actual} differs from ${expected}`);
  }
};
const numeric = (value, label, nonnegative = true) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || (nonnegative && value < -EPSILON)) {
    throw new Error(`${label}: expected a finite ${nonnegative ? 'nonnegative ' : ''}number`);
  }
  return value;
};
const vector = (value, label) => {
  if (!Array.isArray(value) || value.length !== 144) throw new Error(`${label}: expected 144 slots`);
  value.forEach((x, i) => numeric(x, `${label}[${i}]`));
};
const excelDate = (date) => new Date(`${date}T00:00:00.000Z`);
const expectedDates = Array.from({ length: 334 }, (_, i) =>
  new Date(Date.UTC(2025, 1, 1 + i)).toISOString().slice(0, 10));

function validateDay(day, label, annual, adjusted) {
  for (const field of ['plan', 'charge', 'discharge']) vector(day[field], `${label}.${field}`);
  for (const field of ['socStart', 'socEnd']) numeric(day[field], `${label}.${field}`);
  if (annual) {
    vector(day.emergency, `${label}.emergency`);
    numeric(day.planCost, `${label}.planCost`);
  }
  if (adjusted) {
    vector(day.adjusted, `${label}.adjusted`);
    numeric(day.adjustedCost, `${label}.adjustedCost`);
  }
}

function validateResults(results) {
  if (results.schemaVersion !== 1) throw new Error('Expected schemaVersion = 1');
  if (results.slotConvention !== 'right-end-0000-to-2400') {
    throw new Error('Expected slots 00:00-00:10 through 23:50-24:00');
  }
  validateDay(results.q1, 'q1', false, false);
  for (const key of ['q2', 'q3', 'q4_2', 'q4_3']) {
    const days = results[key]?.days;
    if (!Array.isArray(days) || days.length !== 334) throw new Error(`${key}: expected 334 days`);
    days.forEach((day, i) => {
      if (day.date !== expectedDates[i]) throw new Error(`${key}.days[${i}]: incorrect date ${day.date}`);
      validateDay(day, `${key}.${day.date}`, true, key === 'q3' || key === 'q4_3');
    });
  }
}

function groupedEnergy(values) {
  return Array.from({ length: 6 }, (_, i) => sum(values.slice(i * 24, (i + 1) * 24)));
}

function emergencyRows(days) {
  const rows = [];
  for (const day of days) {
    const intervals = [];
    let slot = 0;
    while (slot < 144) {
      if (day.emergency[slot] <= EPSILON) { slot++; continue; }
      const begin = slot;
      let energy = 0;
      while (slot < 144 && day.emergency[slot] > EPSILON) energy += day.emergency[slot++];
      intervals.push([`${time(begin * 10)}-${time(slot * 10)}`, energy]);
    }
    if (!intervals.length) intervals.push(['无紧急购电', 0]);
    close(sum(intervals.map((row) => row[1])), sum(day.emergency), `${day.date}: emergency aggregation`);
    intervals.forEach(([interval, energy], i) => rows.push([i === 0 ? excelDate(day.date) : null, interval, energy]));
  }
  return rows;
}

async function savePreview(workbook, filename, sheet, range, stage) {
  const blob = await workbook.render({ sheetName: sheet, range, scale: 1.5, format: 'png' });
  const name = `${filename.replace('.xlsx', '')}-${sheet}-${stage}.png`;
  await fs.writeFile(path.join(PREVIEWS, name), new Uint8Array(await blob.arrayBuffer()));
}

async function inspectTemplate(workbook, filename) {
  console.log(filename, (await workbook.inspect({ kind: 'sheet', include: 'id,name', maxChars: 2500 })).ndjson);
  for (let i = 0; i < (filename === 'result1.xlsx' ? 2 : filename === 'result3.xlsx' || filename === 'result4-3.xlsx' ? 4 : 3); i++) {
    const sheet = workbook.worksheets.getItemAt(i);
    const range = sheet.name.includes('购电量') && sheet.name !== '紧急购电量'
      ? filename === 'result1.xlsx' ? 'A1:B9' : 'A1:G7'
      : sheet.name === '紧急购电量' ? 'A1:C11' : filename === 'result1.xlsx' ? 'A1:E7' : 'A1:F13';
    console.log((await workbook.inspect({ kind: 'table', range: `${sheet.name}!${range}`, tableMaxRows: 7, tableMaxCols: 7, maxChars: 2000 })).ndjson);
    await savePreview(workbook, filename, sheet.name, range, 'template');
  }
}

function fillPlanSheet(sheet, days, adjusted) {
  sheet.getRange('B1:EO1').values = [INTERVALS];
  const field = adjusted ? 'adjusted' : 'plan';
  const costField = adjusted ? 'adjustedCost' : 'planCost';
  sheet.getRange('B2:EO335').values = days.map((day) => day[field]);
  sheet.getRange('EP2:EP335').formulas = days.map((_, i) => [`=SUM(B${i + 2}:EO${i + 2})`]);
  sheet.getRange('EQ2:EQ335').values = days.map((day) => [day[costField]]);
  sheet.getRange('B2:EQ335').setNumberFormat('0.0000');
}

function fillStorageSheet(sheet, days) {
  // Expand the six-row example in place; preserve tab order and header cells.
  const rows = days.flatMap((day) => {
    const charge = groupedEnergy(day.charge);
    const discharge = groupedEnergy(day.discharge);
    return PERIODS.map((period, i) => [i === 0 ? excelDate(day.date) : null, period,
      charge[i], discharge[i], i === 0 ? 0 : i === 1 ? '24:00' : null,
      i === 0 ? day.socStart : i === 1 ? day.socEnd : null]);
  });
  sheet.getRange(`A2:F${rows.length + 1}`).values = rows;
  sheet.getRange(`A2:A${rows.length + 1}`).setNumberFormat('mm-dd-yy');
  sheet.getRange(`C2:D${rows.length + 1}`).setNumberFormat('0.0000');
  sheet.getRange(`E2:E${rows.length + 1}`).setNumberFormat('h:mm');
  sheet.getRange(`F2:F${rows.length + 1}`).setNumberFormat('0.0000');
  extendTemplateBody(sheet.getRange(`A2:F${rows.length + 1}`));
  for (let i = 0; i < days.length; i++) {
    const start = 2 + i * 6;
    dayBorders(sheet.getRange(`A${start}:F${start + 5}`));
  }
}

function extendTemplateBody(range) {
  // copyFrom(all) did not extend imported cell formatting beyond the original
  // sample rows in this artifact-tool runtime. Explicitly match the template.
  range.format.font = { name: '宋体', size: 10 };
  range.format.horizontalAlignment = 'center';
  range.format.verticalAlignment = 'center';
  range.format.rowHeight = 14;
  range.format.borders = { preset: 'none' };
}

function dayBorders(range) {
  range.format.borders = { top: TEMPLATE_EDGE, bottom: TEMPLATE_EDGE,
    left: TEMPLATE_EDGE, right: TEMPLATE_EDGE, insideVertical: TEMPLATE_EDGE };
}

function fillEmergencySheet(sheet, days) {
  const rows = emergencyRows(days);
  sheet.getRange(`A2:C${Math.max(11, rows.length + 1)}`).clear({ applyTo: 'contents' });
  sheet.getRange(`A2:C${rows.length + 1}`).values = rows;
  sheet.getRange(`A2:A${rows.length + 1}`).setNumberFormat('mm-dd-yy');
  sheet.getRange(`C2:C${rows.length + 1}`).setNumberFormat('0.0000');
  extendTemplateBody(sheet.getRange(`A2:C${rows.length + 1}`));
  let begin = 0;
  for (let i = 1; i <= rows.length; i++) {
    if (i === rows.length || rows[i][0] !== null) {
      dayBorders(sheet.getRange(`A${begin + 2}:C${i + 1}`));
      begin = i;
    }
  }
  return rows.length;
}

async function verifyWorkbook(workbook, filename, result) {
  const plan = workbook.worksheets.getItem('计划购电量');
  if (filename === 'result1.xlsx') {
    const values = plan.getRange('B2:B145').values.flat();
    values.forEach((value, i) => close(value, result.plan[i], `q1 slot ${i}`));
  } else {
    for (const [sheetName, field, costField] of [
      ['计划购电量', 'plan', 'planCost'],
      ...(result.days[0].adjusted ? [['调整购电量', 'adjusted', 'adjustedCost']] : []),
    ]) {
      const sheet = workbook.worksheets.getItem(sheetName);
      const values = sheet.getRange('B2:EQ335').values;
      values.forEach((row, i) => {
        close(sum(row.slice(0, 144)), sum(result.days[i][field]), `${filename} ${sheetName} day ${i}`);
        close(row[144], sum(result.days[i][field]), `${filename} ${sheetName} daily SUM ${i}`);
        close(row[145], result.days[i][costField], `${filename} ${sheetName} cost ${i}`);
      });
    }
  }
  console.log((await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 20 }, summary: `${filename} final formula error scan`, maxChars: 2500 })).ndjson);
}

async function verifySavedFiles(inputPath) {
  const python = process.env.CODEX_BUNDLED_PYTHON
    ?? 'C:/Users/A_Words/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
  // Independent read-only check: no .save(), ExcelWriter or XML mutation.
  const code = String.raw`
import datetime, hashlib, json, math, pathlib, sys
import openpyxl
root, input_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
results = json.loads(input_path.read_text(encoding='utf-8'))
verification = {
    'verification_version': '1.1.0', 'passed': False, 'error_count': 0,
    'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'validator': 'scripts/export_results.mjs --verify',
    'validator_sha256': hashlib.sha256((root/'scripts/export_results.mjs').read_bytes()).hexdigest(),
    'source': {'path': input_path.relative_to(root).as_posix(),
               'sha256': hashlib.sha256(input_path.read_bytes()).hexdigest(),
               'schema_version': results['schemaVersion'], 'slot_convention': results['slotConvention']},
    'engine': {'python': sys.version.split()[0], 'openpyxl': openpyxl.__version__,
               'mode': 'read_only_verification_no_workbook_writes'},
    'limitations': ['Desktop Excel interactive recalculation was not run.'],
    'files': []
}
files = [('result1.xlsx','q1'),('result2.xlsx','q2'),('result3.xlsx','q3'),('result4-2.xlsx','q4_2'),('result4-3.xlsx','q4_3')]
def same(actual, expected):
    assert isinstance(actual, (int,float)) and math.isfinite(actual), (actual, expected)
    assert math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-6), (actual,expected)
def tm(minutes):
    return f'{minutes//60}:{minutes%60:02}'
intervals = [f'{tm(i*10)}-{tm((i+1)*10)}' for i in range(144)]
for filename,key in files:
    saved = root/'outputs/deliverables'/filename
    wb = openpyxl.load_workbook(saved,data_only=True)
    formulas = openpyxl.load_workbook(saved,data_only=False,read_only=True)
    template = openpyxl.load_workbook(root/'data/raw/附件5'/filename,data_only=False)
    assert wb.sheetnames == template.sheetnames
    entry = {'file': 'outputs/deliverables/'+filename, 'sha256': hashlib.sha256(saved.read_bytes()).hexdigest(),
             'bytes': saved.stat().st_size, 'passed': True, 'error_count': 0,
             'sheet_names': wb.sheetnames, 'sheets': [], 'time_headers': [], 'field_counts': {}}
    for sh in wb:
        assert not sh.merged_cells and sh.freeze_panes is None
        assert all(c.data_type != 'e' for row in sh for c in row), (filename,sh.title,'formula error')
        entry['sheets'].append({'name': sh.title, 'rows': sh.max_row, 'columns': sh.max_column,
            'populated_cells': sum(c.value is not None for row in sh for c in row),
            'numeric_cells': sum(isinstance(c.value,(int,float)) and not isinstance(c.value,bool) for row in sh for c in row),
            'formula_cells': sum(c.data_type == 'f' for row in formulas[sh.title] for c in row),
            'error_cells': 0, 'merged_ranges': 0})
        for c in template[sh.title][1]:
            if not (sh.title in ('计划购电量','调整购电量') and key != 'q1' and 2 <= c.column <= 145):
                assert sh.cell(1,c.column).value == c.value, (filename,sh.title,c.coordinate)
    result = results[key]
    if key == 'q1':
        sh = wb['计划购电量']
        assert sh.max_row == 145 and sh.max_column == 2
        for i in range(144):
            assert sh.cell(i+2,1).value == intervals[i]
            same(sh.cell(i+2,2).value,result['plan'][i])
        storage = wb['充放电量']
        for block in range(6):
            same(storage.cell(block+2,2).value,sum(result['charge'][block*24:(block+1)*24]))
            same(storage.cell(block+2,3).value,sum(result['discharge'][block*24:(block+1)*24]))
        same(storage['E2'].value,result['socStart']); same(storage['E3'].value,result['socEnd'])
        entry.update({'date_range': None, 'date_rows': 0, 'storage_rows': 6, 'emergency_rows': 0})
        entry['time_headers'].append({'sheet': sh.title, 'range': 'A2:A145', 'count': 144,
            'first': sh['A2'].value, 'last': sh['A145'].value})
        entry['field_counts'] = {'purchase_values_checked': 144, 'daily_total_values_checked': 0,
            'daily_cost_values_checked': 0, 'daily_total_formulas_spotchecked': 0,
            'storage_energy_values_checked': 12, 'storage_boundary_values_checked': 2,
            'emergency_daily_totals_checked': 0}
        verification['files'].append(entry)
        print(filename,'verified: 144 slots and 6 storage blocks')
        continue
    days = result['days']
    fields = [('计划购电量','plan','planCost')]
    if key in ('q3','q4_3'): fields.append(('调整购电量','adjusted','adjustedCost'))
    entry['purchase_annual_totals'] = []
    for title,field,cost in fields:
        sh = wb[title]
        assert sh.max_row == 335 and sh.max_column == 147
        assert [sh.cell(1,i+2).value for i in range(144)] == intervals
        entry['time_headers'].append({'sheet': title, 'range': 'B1:EO1', 'count': 144,
            'first': sh['B1'].value, 'last': sh['EO1'].value})
        for i,day in enumerate(days):
            r = i+2
            assert sh.cell(r,1).value.strftime('%Y-%m-%d') == day['date']
            for j,v in enumerate(day[field]): same(sh.cell(r,j+2).value,v)
            same(sh.cell(r,146).value,sum(day[field])); same(sh.cell(r,147).value,day[cost])
        for i in (0,167,333):
            r = i+2
            assert formulas[title].cell(r,146).value == f'=SUM(B{r}:EO{r})'
        annual_energy = sum(sh.cell(i+2,146).value for i in range(len(days)))
        annual_cost = sum(sh.cell(i+2,147).value for i in range(len(days)))
        same(annual_energy, sum(sum(day[field]) for day in days))
        same(annual_cost, sum(day[cost] for day in days))
        entry['purchase_annual_totals'].append({'sheet': title, 'energy_kwh': annual_energy,
            'cost_yuan': annual_cost, 'last_date': days[-1]['date'],
            'last_day_energy_kwh': sh['EP335'].value, 'last_day_cost_yuan': sh['EQ335'].value})
    # The adjusted sheet already includes the original plan charge. Its EQ
    # sum plus emergency fees is the all-in cost; never add both sheets' EQ.
    delivery_cost = entry['purchase_annual_totals'][-1]['cost_yuan']
    if all('emergencyCost' in day and 'totalCost' in day for day in days):
        emergency_cost = sum(day['emergencyCost'] for day in days)
        same(delivery_cost+emergency_cost, sum(day['totalCost'] for day in days))
        entry['cost_reconciliation'] = {'delivery_cost_yuan': delivery_cost,
            'emergency_cost_yuan_from_source_json': emergency_cost,
            'all_in_cost_yuan': delivery_cost+emergency_cost,
            'adds_plan_sheet_again': False}
    storage = wb['充放电量']
    assert storage.max_row == 2005 and storage.max_column == 6
    for i,day in enumerate(days):
        r = i*6+2
        assert storage.cell(r,1).value.strftime('%Y-%m-%d') == day['date']
        for block in range(6):
            same(storage.cell(r+block,3).value,sum(day['charge'][block*24:(block+1)*24]))
            same(storage.cell(r+block,4).value,sum(day['discharge'][block*24:(block+1)*24]))
        same(storage.cell(r,6).value,day['socStart']); same(storage.cell(r+1,6).value,day['socEnd'])
        assert all(storage.cell(r+b,6).value is None for b in range(2,6))
    emergency = wb['紧急购电量']
    daily = {}; current = None; previous_end = None
    for date,interval,energy in emergency.iter_rows(min_row=2,max_col=3,values_only=True):
        if date is not None:
            current = date.strftime('%Y-%m-%d'); daily[current]=0; previous_end=None
        assert current is not None and interval is not None
        daily[current] += energy
        if interval == '无紧急购电':
            same(energy,0)
        else:
            start,end = interval.split('-')
            start = int(start.split(':')[0])*60+int(start.split(':')[1])
            end = int(end.split(':')[0])*60+int(end.split(':')[1])
            assert 0 <= start < end <= 1440 and start%10 == end%10 == 0
            assert previous_end is None or start > previous_end
            previous_end=end
    assert list(daily) == [d['date'] for d in days]
    for day in days: same(daily[day['date']],sum(day['emergency']))
    entry.update({'date_range': {'first': days[0]['date'], 'last': days[-1]['date']},
                  'date_rows': len(days), 'storage_rows': storage.max_row-1,
                  'emergency_rows': emergency.max_row-1})
    entry['field_counts'] = {'purchase_values_checked': len(fields)*len(days)*144,
        'daily_total_values_checked': len(fields)*len(days),
        'daily_cost_values_checked': len(fields)*len(days),
        'daily_total_formulas_spotchecked': len(fields)*3,
        'storage_energy_values_checked': len(days)*12,
        'storage_boundary_values_checked': len(days)*2,
        'emergency_daily_totals_checked': len(days)}
    verification['files'].append(entry)
    print(filename,'verified: 334 dates,',len(fields)*334*144,'purchase values, 2004 storage rows,',emergency.max_row-1,'emergency rows')
verification['passed'] = True
verification['file_count'] = len(verification['files'])
verification['field_counts'] = {field: sum(f['field_counts'][field] for f in verification['files'])
                                 for field in verification['files'][0]['field_counts']}
(root/'outputs/verification').mkdir(parents=True, exist_ok=True)
(root/'outputs/verification/workbook-verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Saved outputs/verification/workbook-verification.json; all five workbooks passed.')
`;
  try {
    console.log(execFileSync(python, ['-c', code, ROOT, inputPath], { encoding: 'utf8', maxBuffer: 1024 * 1024 }));
  } catch (error) {
    // Never leave an older passed report in place after a failed verification.
    await fs.mkdir(path.join(ROOT, 'outputs/verification'), { recursive: true });
    await fs.writeFile(path.join(ROOT, 'outputs/verification/workbook-verification.json'), JSON.stringify({
      verification_version: '1.1.0', passed: false, error_count: 1,
      generated_at: new Date().toISOString(), validator: 'scripts/export_results.mjs --verify',
      errors: [String(error.stderr ?? error.message)],
    }, null, 2));
    throw new Error('Saved workbook verification failed; see outputs/verification/workbook-verification.json for details.');
  }
}

async function main() {
  await fs.mkdir(PREVIEWS, { recursive: true });
  const junction = path.join(PREVIEWS, 'node_modules');
  try { await fs.access(junction); } catch { await fs.symlink(BUNDLED_MODULES, junction, 'junction'); }
  const require = createRequire(path.join(PREVIEWS, 'loader.cjs'));
  const { FileBlob, SpreadsheetFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
  const inspectOnly = process.argv.includes('--inspect');
  const filesArg = process.argv.find((value) => value.startsWith('--files='));
  const requestedFiles = filesArg ? filesArg.slice(8).split(',').map((value) => value.trim()) : null;
  if (requestedFiles && (requestedFiles.some((filename) => !FILES.some(([known]) => known === filename))
    || new Set(requestedFiles).size !== requestedFiles.length)) {
    throw new Error('--files must contain distinct supported filenames separated by commas');
  }
  const selectedFiles = requestedFiles ? FILES.filter(([filename]) => requestedFiles.includes(filename)) : FILES;
  const inputArg = process.argv.find((value) => value.startsWith('--input='));
  const inputPath = inputArg ? path.resolve(inputArg.slice(8)) : path.join(ROOT, 'outputs/main/results.json');
  const results = inspectOnly ? null : JSON.parse(await fs.readFile(inputPath, 'utf8'));
  if (results) validateResults(results);
  if (process.argv.includes('--verify')) { await verifySavedFiles(inputPath); return; }
  if (process.argv.includes('--preview-saved')) {
    for (const [filename, key] of selectedFiles.filter(([, key]) => key !== 'q1')) {
      const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(OUTPUT, filename)));
      await savePreview(workbook, filename, '计划购电量', 'EM1:EQ7', 'saved-totals');
      await savePreview(workbook, filename, '计划购电量', 'EM329:EQ335', 'saved-year-end');
      if (key === 'q3' || key === 'q4_3') {
        await savePreview(workbook, filename, '调整购电量', 'A1:H7', 'final');
        await savePreview(workbook, filename, '调整购电量', 'AK1:AR7', 'saved-0600');
        await savePreview(workbook, filename, '调整购电量', 'EM1:EQ8', 'saved-totals');
        await savePreview(workbook, filename, '调整购电量', 'EM329:EQ335', 'saved-year-end');
      }
      await savePreview(workbook, filename, '充放电量', 'A1994:F2005', 'saved-tail');
      const last = emergencyRows(results[key].days).length + 1;
      await savePreview(workbook, filename, '紧急购电量', `A${last - 10}:C${last}`, 'saved-tail');
    }
    return;
  }
  const audit = [];
  for (const [filename, key] of selectedFiles) {
    const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(ROOT, 'data', 'raw', '附件5', filename)));
    if (inspectOnly) { await inspectTemplate(workbook, filename); continue; }
    const result = results[key];
    let emergencyCount = null;
    if (key === 'q1') {
      const plan = workbook.worksheets.getItem('计划购电量');
      plan.getRange('A2:A145').values = INTERVALS.map((interval) => [interval]);
      plan.getRange('B2:B145').values = result.plan.map((value) => [value]);
      const storage = workbook.worksheets.getItem('充放电量');
      const charge = groupedEnergy(result.charge);
      const discharge = groupedEnergy(result.discharge);
      storage.getRange('B2:C7').values = PERIODS.map((_, i) => [charge[i], discharge[i]]);
      storage.getRange('E2:E3').values = [[result.socStart], [result.socEnd]];
      storage.getRange('B2:C7').setNumberFormat('0.0000');
      storage.getRange('E2:E3').setNumberFormat('0.0000');
    } else {
      fillPlanSheet(workbook.worksheets.getItem('计划购电量'), result.days, false);
      if (key === 'q3' || key === 'q4_3') fillPlanSheet(workbook.worksheets.getItem('调整购电量'), result.days, true);
      fillStorageSheet(workbook.worksheets.getItem('充放电量'), result.days);
      emergencyCount = fillEmergencySheet(workbook.worksheets.getItem('紧急购电量'), result.days);
    }
    workbook.recalculate();
    await verifyWorkbook(workbook, filename, result);
    for (let i = 0; i < (key === 'q1' ? 2 : key === 'q3' || key === 'q4_3' ? 4 : 3); i++) {
      const sheet = workbook.worksheets.getItemAt(i);
      const range = sheet.name === '充放电量' ? key === 'q1' ? 'A1:E7' : 'A1:F13'
        : sheet.name === '紧急购电量' ? 'A1:C14' : key === 'q1' ? 'A1:B10'
          : sheet.name === '调整购电量' ? 'A1:H7' : 'A1:G7';
      await savePreview(workbook, filename, sheet.name, range, 'final');
    }
    await fs.mkdir(OUTPUT, { recursive: true });
    await (await SpreadsheetFile.exportXlsx(workbook)).save(path.join(OUTPUT, filename));
    const automaticInspect = path.join(OUTPUT, `${filename}.inspect.ndjson`);
    try { await fs.rename(automaticInspect, path.join(PREVIEWS, `${filename}.inspect.ndjson`)); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    audit.push({ filename, days: key === 'q1' ? 1 : 334, slots: 144, emergencyRows: emergencyCount });
    console.log(`Saved ${filename}`);
  }
  if (!inspectOnly) {
    await verifySavedFiles(inputPath);
    await fs.writeFile(path.join(PREVIEWS, 'export-audit.json'), JSON.stringify(audit, null, 2));
  }
}

await main();
