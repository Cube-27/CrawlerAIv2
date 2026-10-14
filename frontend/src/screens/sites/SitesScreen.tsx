import { Button, Description, Form, Input, Label, TextField } from "@heroui/react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { FormActions } from "../../components/FormActions";
import { PageHeader } from "../../components/PageHeader";
import { sitePath } from "./paths";

/** Opens a site's configs by host. The API reads configs per host (`GET /v1/sites/{host}/configs`) and has no list
 * of sites, so the host is entered here. */
export function SitesScreen() {
  const navigate = useNavigate();
  const [host, setHost] = useState("");
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Sites" />
      <Form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void navigate(sitePath(host.trim()));
        }}
      >
        <TextField isRequired value={host} onChange={setHost}>
          <Label>Host</Label>
          <Input autoComplete="off" spellCheck={false} />
          <Description>The site's host name, as its records name it.</Description>
        </TextField>
        <FormActions>
          <Button type="submit">Open site</Button>
        </FormActions>
      </Form>
    </section>
  );
}
