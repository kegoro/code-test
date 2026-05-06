import { AppShell } from "@/components/layout/AppShell";
import { DashboardClient } from "@/components/dashboard/DashboardClient";

export default function Page() {
  return (
    <AppShell>
      <DashboardClient />
    </AppShell>
  );
}
