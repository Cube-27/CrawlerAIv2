import { Button, FieldError, Form, Input, Label, TextField, Typography } from "@heroui/react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { useAuth } from "../../app/auth";
import { FormActions } from "../../components/FormActions";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";

// RequireKey passes the path the viewer asked for as `state.from`.
function returnPath(state: unknown): string {
  if (typeof state === "object" && state !== null && "from" in state) {
    const { from } = state;
    if (typeof from === "string") return from;
  }
  return "/";
}

export function ConnectScreen() {
  const { connect, rejection } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [apiKey, setApiKey] = useState("");

  return (
    <section className="flex max-w-md flex-col gap-4">
      <PageHeader title="Connect" />
      <Typography.Paragraph color="muted">
        Enter an API key created with <Typography.Code>crawlerai apikey create</Typography.Code>.
        The key stays in this tab&apos;s memory and is sent as a bearer header; reloading the page
        forgets it.
      </Typography.Paragraph>
      {rejection === null ? null : <ProblemAlert problem={rejection} />}
      <Form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          // RFC 6750 §2.1: a bearer token has no whitespace, so whitespace around a pasted key is not part of it.
          connect(apiKey.trim());
          void navigate(returnPath(location.state), { replace: true });
        }}
      >
        <TextField
          isRequired
          type="password"
          name="apiKey"
          value={apiKey}
          onChange={setApiKey}
          validate={(value) => (value.trim() === "" ? "Enter an API key." : null)}
        >
          <Label>API key</Label>
          <Input autoComplete="off" />
          <FieldError />
        </TextField>
        <FormActions>
          <Button type="submit">Connect</Button>
        </FormActions>
      </Form>
    </section>
  );
}
