import { AdminShell } from "@/components/admin/AdminShell";
import { LogsDashboard } from "@/components/admin/LogsDashboard";

export default function AdminLogsPage() {
  return <AdminShell title="问答日志" path="/admin/logs"><LogsDashboard /></AdminShell>;
}
