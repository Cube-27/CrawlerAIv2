import { createContext } from "react";

/** Whether the playground shows a run's request rather than one being edited: the command bar's input
 * and tools and the options' controls are then disabled, while the options can still be opened and read. */
export const ReadOnlyContext = createContext(false);
