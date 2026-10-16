import { Card } from "@heroui/react";
import { useNavigate } from "react-router";
import { LookupForm } from "../../components/LookupForm";
import { PageHeader } from "../../components/PageHeader";
import { sitePath } from "./paths";

/** Opens a site's configs by host. The API reads configs per host (`GET /v1/sites/{host}/configs`) and has no list
 * of sites, so the host is entered here. */
export function SitesScreen() {
  const navigate = useNavigate();
  return (
    <section className="flex flex-col gap-stack">
      <PageHeader
        title="Sites"
        description="Each site keeps its learned configs: review them, correct a field, or learn again."
      />
      <Card>
        <Card.Header>
          <Card.Title>Open a site</Card.Title>
          <Card.Description>Enter the site's host name, as its records name it.</Card.Description>
        </Card.Header>
        <Card.Content>
          <LookupForm
            label="Host"
            placeholder="shop.example.com"
            submitLabel="Open site"
            onOpen={(host) => void navigate(sitePath(host))}
          />
        </Card.Content>
      </Card>
    </section>
  );
}
