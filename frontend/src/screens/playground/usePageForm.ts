import { useMemo, useState } from "react";
import { fieldErrors, type Problem } from "../../api/problem";
import { NO_ERRORS } from "./pageRequest";

/** The state of a mode's form: the form, whether its options panel is open, and its errors: the server's `problem` by
 * field, then why the form can't be sent (`errorsOf`, `NO_ERRORS` when it can) once a send was refused. */
export function usePageForm<F>(
  initial: F,
  problem: Problem | null,
  errorsOf: (form: F) => Readonly<Record<string, string>>,
) {
  const [form, setForm] = useState<F>(initial);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [refused, setRefused] = useState(false);
  const clientErrors = refused ? errorsOf(form) : NO_ERRORS;
  const validationErrors = useMemo(
    () => ({ ...(problem === null ? NO_ERRORS : fieldErrors(problem)), ...clientErrors }),
    [problem, clientErrors],
  );
  /** Whether the form can be sent. When it can't, its errors show; a reason other than the toolbar's formats opens the
   * options, where the setting is. */
  const check = (): boolean => {
    const errors = errorsOf(form);
    const sendable = errors === NO_ERRORS;
    setRefused(!sendable);
    if (!sendable && !("formats" in errors)) setOptionsOpen(true);
    return sendable;
  };
  return { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check };
}
