import { useMemo, useState } from "react";
import { fieldErrors, type Problem } from "../../api/problem";
import {
  asksForNothing,
  canSend,
  NO_ERRORS,
  pageKindErrors,
  type PageKindForm,
} from "./pageRequest";

/** The state of a mode whose request names one page kind (Scrape, Batch): the form, whether its options panel is open,
 * and its errors: the server's `problem` by field, then why the form can't be sent once a send was refused. */
export function usePageForm<F extends PageKindForm>(initial: F, problem: Problem | null) {
  const [form, setForm] = useState<F>(initial);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [refused, setRefused] = useState(false);
  const clientErrors = refused ? pageKindErrors(form) : NO_ERRORS;
  const validationErrors = useMemo(
    () => ({ ...(problem === null ? NO_ERRORS : fieldErrors(problem)), ...clientErrors }),
    [problem, clientErrors],
  );
  /** Whether the form can be sent. When it can't, its errors show; a page-kind reason opens the options, where the
   * page kind is. */
  const check = (): boolean => {
    const sendable = canSend(form);
    setRefused(!sendable);
    if (!sendable && !asksForNothing(form)) setOptionsOpen(true);
    return sendable;
  };
  return { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check };
}
