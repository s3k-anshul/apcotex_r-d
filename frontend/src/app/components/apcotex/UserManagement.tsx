import React, { useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { Users, Plus, Key, XCircle, CheckCircle, X } from 'lucide-react';
import { PasswordInput } from './PasswordInput';

export const UserManagement: React.FC = () => {
  const { user } = useAuth();
  const [usersList, setUsersList] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);

  // Form states
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("SCIENTIST");

  const BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api/v1';
  
  const fetchUsers = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE_URL}/users`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error("Failed to fetch users");
      const data = await res.json();
      setUsersList(data.data);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const deactivateUser = async (id: string) => {
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE_URL}/users/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error?.message || "Failed to deactivate");
      }
      await fetchUsers();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleAddUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE_URL}/users`, {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          username, email, password, full_name: fullName, role
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error?.message || "Failed to add user");
      }
      setIsAddModalOpen(false);
      setUsername(""); setEmail(""); setPassword(""); setFullName(""); setRole("SCIENTIST");
      await fetchUsers();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE_URL}/users/${selectedUser.id}/password`, {
        method: 'PATCH',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ password })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error?.message || "Failed to change password");
      }
      setIsPasswordModalOpen(false);
      setSelectedUser(null);
      setPassword("");
      alert("Password changed successfully");
    } catch (e: any) {
      alert(e.message);
    }
  };

  if (user?.role !== 'ADMIN') return null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden mt-8">
      <div className="px-6 py-4 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center">
          <Users className="text-indigo-600 mr-2" size={20} />
          <h2 className="text-lg font-semibold text-gray-800">User Management</h2>
        </div>
        <button 
          onClick={() => setIsAddModalOpen(true)}
          className="text-sm bg-indigo-600 text-white px-3 py-1.5 rounded-md flex items-center hover:bg-indigo-700 transition-colors"
        >
          <Plus size={16} className="mr-1" /> Add User / Admin
        </button>
      </div>
      <div className="p-6">
        {error && <p className="text-red-500 mb-4">{error}</p>}
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead>
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Username</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Role</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {usersList.map((u: any) => (
                <tr key={u.id}>
                  <td className="px-4 py-3 text-sm text-gray-900 font-medium">{u.username}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{u.role === 'SCIENTIST' ? 'USER' : u.role}</td>
                  <td className="px-4 py-3 text-sm">
                    {u.is_active ? 
                      <span className="text-green-600 flex items-center"><CheckCircle size={14} className="mr-1" /> Active</span> :
                      <span className="text-red-500 flex items-center"><XCircle size={14} className="mr-1" /> Inactive</span>
                    }
                  </td>
                  <td className="px-4 py-3 text-sm text-right space-x-3">
                    <button 
                      onClick={() => { setSelectedUser(u); setIsPasswordModalOpen(true); }}
                      className="text-indigo-600 hover:text-indigo-900 inline-flex items-center" 
                      title="Change Password"
                    >
                      <Key size={16} />
                    </button>
                    {u.is_active && (
                      <button onClick={() => deactivateUser(u.id)} className="text-red-600 hover:text-red-900 inline-flex items-center" title="Deactivate">
                        <XCircle size={16} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add User Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-medium text-gray-900">Add New User</h3>
              <button onClick={() => setIsAddModalOpen(false)} className="text-gray-400 hover:text-gray-500">
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleAddUser} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input required type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                <input required type="text" value={fullName} onChange={e => setFullName(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input required type="email" value={email} onChange={e => setEmail(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select value={role} onChange={e => setRole(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-indigo-500">
                  <option value="SCIENTIST">User</option>
                  <option value="ADMIN">Admin</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <PasswordInput required value={password} onChange={e => setPassword(e.target.value)} minLength={8} />
              </div>
              <div className="pt-4 flex justify-end space-x-3">
                <button type="button" onClick={() => setIsAddModalOpen(false)} className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700">Add User</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Change Password Modal */}
      {isPasswordModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-medium text-gray-900">Change Password</h3>
              <button onClick={() => {setIsPasswordModalOpen(false); setPassword("");}} className="text-gray-400 hover:text-gray-500">
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleChangePassword} className="p-6 space-y-4">
              <p className="text-sm text-gray-500">Changing password for <span className="font-semibold text-gray-800">{selectedUser?.username}</span></p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New Password</label>
                <PasswordInput required value={password} onChange={e => setPassword(e.target.value)} minLength={8} />
              </div>
              <div className="pt-4 flex justify-end space-x-3">
                <button type="button" onClick={() => {setIsPasswordModalOpen(false); setPassword("");}} className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700">Save</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
