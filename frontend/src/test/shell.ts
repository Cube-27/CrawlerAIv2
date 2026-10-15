/** Reads shell words back as POSIX sh would (POSIX.1-2017 XCU §2.2): enough of the grammar to check the snippets Get
 * code writes, which quote every word with single quotes and write a quote as `'\''`. */

/** The word made of single-quoted parts and `\'` starting at `start` in `text`. */
export function shellWordAt(text: string, start: number): string {
  let word = "";
  let at = start;
  for (;;) {
    if (text[at] !== "'") throw new Error(`no quoted word at ${String(at)}`);
    const close = text.indexOf("'", at + 1);
    if (close === -1) throw new Error("unterminated quote");
    word += text.slice(at + 1, close);
    at = close + 1;
    if (!text.startsWith("\\'", at)) return word;
    word += "'";
    at += 2;
  }
}

/** The JSON body a cURL snippet sends: its `-d` word, parsed. */
export function curlBody(snippet: string): unknown {
  const flag = snippet.indexOf("-d '");
  if (flag === -1) throw new Error("no -d word");
  return JSON.parse(shellWordAt(snippet, flag + 3));
}
