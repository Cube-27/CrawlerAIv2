# Tasks

## 1. Paged lists

- [ ] 1.1 Let an adapter fetch every page of a list through `send`, merged into one capture, bounded by
      `fetch.max_rows` and a hard cap; Workday CXS (20 per page, offset, total on the first page, short page ends) and
      Oracle Recruiting (100 per page, until `TotalJobsCount`).

## 2. Workday on a tenant's own host

- [ ] 2.1 Serve a page on another host that points to a Workday career site (final URL, canonical, `og:url`, links)
      from that site's endpoints.

## 3. More adapters

- [ ] 3.1 Ashby, SmartRecruiters, Recruitee, Workable and Rippling adapters with `JobPosting` shapes, registered;
      salary as a `MonetaryAmount` node read as a schema.org object.

## 4. Spec and decision

- [ ] 4.1 Owner decision #57 (admission of the adapters), the adapters spec, and archive this change.
