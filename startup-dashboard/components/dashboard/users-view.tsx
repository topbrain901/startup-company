"use client";

import { ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { shortDate } from "../../lib/format";
import type { Me, Profile, Role } from "../../lib/types";

type Notify = (message: string, tone?: "info" | "error" | "success") => void;

export default function UsersView({ me, notify }: { me: Me; notify: Notify }) {
  const [users, setUsers] = useState<Profile[] | null>(null);
  const [saving, setSaving] = useState("");

  const load = useCallback(() => {
    api<Profile[]>("admin/users")
      .then(setUsers)
      .catch((reason) => notify(reason instanceof Error ? reason.message : "Could not load users", "error"));
  }, [notify]);
  useEffect(() => load(), [load]);

  async function setRole(user: Profile, role: Role) {
    setSaving(user.id);
    try {
      const updated = await api<Profile>(`admin/users/${user.id}/role`, { method: "PATCH", json: { role } });
      setUsers((current) => current?.map((item) => (item.id === user.id ? { ...item, role: updated.role } : item)) || null);
      notify(`${user.email} is now ${role === "admin" ? "an administrator" : "a user"}`, "success");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not change role", "error");
    } finally {
      setSaving("");
    }
  }

  return (
    <section className="content-wrap">
      <div className="page-heading">
        <div><h2>Users</h2><p>People sign up on the login page. Administrators can run scrapes and edit or delete data; users can browse, take notes, and track what they have viewed.</p></div>
      </div>
      <div className="panel">
        <div className="table-scroll">
          <table className="simple-table">
            <thead><tr><th>Email</th><th>Role</th><th>Joined</th></tr></thead>
            <tbody>
              {!users && <tr><td colSpan={3} className="muted">Loading…</td></tr>}
              {users?.map((user) => (
                <tr key={user.id}>
                  <td>{user.email || user.id}{user.id === me.id && <span className="you-tag">you</span>}</td>
                  <td>
                    <div className="role-cell">
                      {user.role === "admin" && <ShieldCheck size={15} className="admin-icon" />}
                      <select
                        className="native-select small"
                        value={user.role}
                        disabled={saving === user.id || user.id === me.id}
                        onChange={(event) => void setRole(user, event.target.value as Role)}
                        aria-label={`Role for ${user.email}`}
                      >
                        <option value="user">User</option>
                        <option value="admin">Administrator</option>
                      </select>
                    </div>
                  </td>
                  <td>{shortDate(user.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
