import { Alert } from "@heroui/react";
import type { ReactNode } from "react";
import type { ProblemSummary } from "../api/problem";

/** An RFC 9457 problem from the API, shown the same way on every screen (SPEC-12 §4.5). `children` are more lines
 * under the detail, as `Alert.Description`s: the problem's per-field errors, for one. */
export function ProblemAlert({
  problem,
  children,
}: Readonly<{ problem: ProblemSummary; children?: ReactNode }>) {
  return (
    <Alert status="danger" role="alert">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{problem.title}</Alert.Title>
        {problem.detail === null ? null : <Alert.Description>{problem.detail}</Alert.Description>}
        {children}
      </Alert.Content>
    </Alert>
  );
}
