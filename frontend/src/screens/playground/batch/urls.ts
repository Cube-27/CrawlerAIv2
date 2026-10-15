/** The URL list of the Batch command bar (SPEC-14 §4.2): one URL per line, filled by hand or from a CSV file. */

/** The non-blank lines of `text`, trimmed: a list entered one entry per line. */
export function lines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** `list` (one URL per line) with `added` appended, leaving out a URL already listed, by exact string. */
export function appendUrls(list: string, added: readonly string[]): string {
  const urls = lines(list);
  const seen = new Set(urls);
  for (const url of added) {
    if (!seen.has(url)) {
      seen.add(url);
      urls.push(url);
    }
  }
  return urls.join("\n");
}

/** A CSV file being read (RFC 4180 §2): the records so far, and the record and field being read. */
interface CsvReader {
  records: string[][];
  record: string[];
  field: string;
  quoted: boolean;
}

function endField(reader: CsvReader): void {
  reader.record.push(reader.field);
  reader.field = "";
}

function endRecord(reader: CsvReader): void {
  endField(reader);
  reader.records.push(reader.record);
  reader.record = [];
}

/** One step inside a quoted field, which may hold commas and line breaks; `""` is a quote (RFC 4180 §2.7). Returns
 * how many characters it read. */
function readQuoted(reader: CsvReader, char: string, next: string): number {
  if (char !== '"') {
    reader.field += char;
    return 1;
  }
  if (next === '"') {
    reader.field += '"';
    return 2;
  }
  reader.quoted = false;
  return 1;
}

/** One step outside quotes: a comma ends a field, a line break a record (RFC 4180 §2.1, §2.4). CRLF, LF and CR all
 * end a record, as files saved on any system have them. */
function readPlain(reader: CsvReader, char: string, next: string): number {
  if (char === '"') {
    reader.quoted = true;
    return 1;
  }
  if (char === ",") {
    endField(reader);
    return 1;
  }
  if (char === "\r" || char === "\n") {
    endRecord(reader);
    return char === "\r" && next === "\n" ? 2 : 1;
  }
  reader.field += char;
  return 1;
}

function csvRecords(text: string): string[][] {
  const reader: CsvReader = { records: [], record: [], field: "", quoted: false };
  for (let i = 0; i < text.length;) {
    const read = reader.quoted ? readQuoted : readPlain;
    i += read(reader, text.charAt(i), text.charAt(i + 1));
  }
  // RFC 4180 §2.2: the last record may have no line break after it.
  if (reader.field !== "" || reader.record.length > 0) endRecord(reader);
  return reader.records;
}

// RFC 4180 §2.3: the first record may be a header; it is one when a field of it names the `url` column.
const URL_HEADER = "url";

/** The URLs in a CSV file's `text`: the `url` column's values when the first record has that header, else each
 * record's first field; blank fields are left out. */
export function csvUrls(text: string): string[] {
  const records = csvRecords(text);
  const header = (records[0] ?? []).map((name) => name.trim().toLowerCase());
  const column = header.indexOf(URL_HEADER);
  const rows = column === -1 ? records : records.slice(1);
  return rows.map((row) => (row[Math.max(column, 0)] ?? "").trim()).filter((url) => url !== "");
}
