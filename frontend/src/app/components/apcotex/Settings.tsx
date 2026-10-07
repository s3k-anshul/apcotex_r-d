import React, { useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { settingsApi, LLMSettings, ProviderInfo } from '../../services/settingsApi';
import { 
  Cpu, 
  CheckCircle, 
  AlertTriangle, 
  XCircle, 
  Save, 
  Settings as SettingsIcon 
} from 'lucide-react';
import { UserManagement } from './UserManagement';

export const SettingsPage: React.FC = () => {
  const { user } = useAuth();
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      setIsLoading(true);
      const data = await settingsApi.getLLMSettings();
      setSettings(data);
      setSelectedProvider(data.active_provider);
    } catch (err: any) {
      setError(err.message || 'Failed to load settings');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      setIsSaving(true);
      setError(null);
      setSuccessMsg(null);
      await settingsApi.updateLLMProvider(selectedProvider);
      setSuccessMsg('Provider configuration saved successfully.');
      await fetchSettings(); // Refresh status
    } catch (err: any) {
      setError(err.message || 'Failed to update provider');
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-spin text-blue-500">
          <SettingsIcon size={32} />
        </div>
      </div>
    );
  }

  if (user && user.role !== 'ADMIN') {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center p-8 bg-white rounded-xl shadow border border-red-200">
          <AlertTriangle size={48} className="mx-auto text-red-500 mb-4" />
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h2>
          <p className="text-gray-600">You do not have permission to view this page.</p>
        </div>
      </div>
    );
  }

  const selectedProviderInfo = settings?.providers.find(p => p.id === selectedProvider);

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-2 flex items-center">
          <SettingsIcon className="mr-2" /> Application Settings
        </h1>
        <p className="text-gray-600">
          Configure application-wide preferences.
        </p>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50 flex items-center">
          <Cpu className="text-indigo-600 mr-2" size={20} />
          <h2 className="text-lg font-semibold text-gray-800">AI Model Configuration</h2>
        </div>

        <div className="p-6">
          <p className="text-sm text-gray-600 mb-6">
            Select the primary Large Language Model provider that will power the APCOTEX R&D workflow. 
            This provider will be used globally for patent research, recipe generation, and other AI features.
          </p>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border-l-4 border-red-500 text-red-700 rounded flex items-start">
              <AlertTriangle className="mr-2 flex-shrink-0 mt-0.5" size={18} />
              <p>{error}</p>
            </div>
          )}

          {successMsg && (
            <div className="mb-6 p-4 bg-green-50 border-l-4 border-green-500 text-green-700 rounded flex items-start">
              <CheckCircle className="mr-2 flex-shrink-0 mt-0.5" size={18} />
              <p>{successMsg}</p>
            </div>
          )}

          <div className="mb-8">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Primary AI Provider
            </label>
            <div className="relative">
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                className="block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md shadow-sm border"
              >
                {settings?.providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.status !== 'Configured' ? `(${p.status})` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {selectedProviderInfo && (
            <div className="bg-gray-50 rounded-lg p-5 border border-gray-200 mb-6">
              <h3 className="text-sm font-semibold text-gray-900 uppercase tracking-wider mb-4">
                Provider Details
              </h3>
              
              <dl className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
                <div className="sm:col-span-1">
                  <dt className="text-sm font-medium text-gray-500">Provider</dt>
                  <dd className="mt-1 text-sm text-gray-900">{selectedProviderInfo.name}</dd>
                </div>
                
                <div className="sm:col-span-1">
                  <dt className="text-sm font-medium text-gray-500">Status</dt>
                  <dd className="mt-1 text-sm flex items-center">
                    {selectedProviderInfo.status === 'Configured' ? (
                      <span className="inline-flex items-center text-green-700">
                        <CheckCircle size={16} className="mr-1" />
                        {selectedProviderInfo.status}
                      </span>
                    ) : selectedProviderInfo.status === 'API Key Missing' ? (
                      <span className="inline-flex items-center text-yellow-600">
                        <AlertTriangle size={16} className="mr-1" />
                        {selectedProviderInfo.status}
                      </span>
                    ) : (
                      <span className="inline-flex items-center text-red-600">
                        <XCircle size={16} className="mr-1" />
                        {selectedProviderInfo.status}
                      </span>
                    )}
                  </dd>
                </div>

                <div className="sm:col-span-2">
                  <dt className="text-sm font-medium text-gray-500">Model</dt>
                  <dd className="mt-1 text-sm text-gray-900">{selectedProviderInfo.description}</dd>
                </div>

                <div className="sm:col-span-2">
                  <dt className="text-sm font-medium text-gray-500">API Key</dt>
                  <dd className="mt-1 text-sm text-gray-700">
                    Keys stay in the server environment. This page only selects the primary provider.
                  </dd>
                </div>

                <div className="sm:col-span-2">
                  <dt className="text-sm font-medium text-gray-500">Capabilities</dt>
                  <dd className="mt-2 text-sm text-gray-900">
                    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {selectedProviderInfo.capabilities.map((cap, idx) => (
                        <li key={idx} className="flex items-center">
                          <CheckCircle size={14} className="text-green-500 mr-2" />
                          {cap}
                        </li>
                      ))}
                    </ul>
                  </dd>
                </div>
              </dl>
            </div>
          )}

          <div className="flex justify-end pt-4 border-t border-gray-200">
            <button
              onClick={handleSave}
              disabled={isSaving}
              className={`inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 ${
                isSaving ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              <Save size={16} className="mr-2" />
              {isSaving ? 'Saving...' : 'Save Configuration'}
            </button>
          </div>
        </div>
      </div>
      <UserManagement />
    </div>
  );
};
