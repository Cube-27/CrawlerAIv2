import { Alert } from "@heroui/react";
import type { ProblemSummary } from "../api/problem";

/** An RFC 9457 problem from the API, shown the same way on every screen (SPEC-12 §4.5). */
export function ProblemAlert({ problem }: Readonly<{ problem: ProblemSummary }>) {
  return (
    <Alert status="danger" role="alert">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{problem.title}</Alert.Title>
        {problem.detail === null ? null : <Alert.Description>{problem.detail}</Alert.Description>}
      </Alert.Content>
    </Alert>
  );
}
