import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { api, type Identity } from '@/app/api'
import { Shell } from '@/app/Shell'
import { DeveloperPage } from '@/app/DeveloperPage'
import { SignInPage } from '@/features/auth/SignInPage'
import { signInReturn } from '@/features/auth/signInReturn'

const UsersPage = lazy(() => import('@/features/users/UsersPage').then(module => ({ default: module.UsersPage })))
const ProjectsPage = lazy(() => import('@/features/projects/ProjectsPage').then(module => ({ default: module.ProjectsPage })))
const DataClassesPage = lazy(() => import('@/features/data-classes/DataClassesPage').then(module => ({ default: module.DataClassesPage })))
const AuditPage = lazy(() => import('@/features/audit/AuditPage').then(module => ({ default: module.AuditPage })))
const ModelsPage = lazy(() => import('@/features/models/ModelsPage').then(module => ({ default: module.ModelsPage })))
const EditionsPage = lazy(() => import('@/features/editions/EditionsPage').then(module => ({ default: module.EditionsPage })))

export default function App() {
  const [identity, setIdentity] = useState<Identity | null | undefined>(undefined)
  const refresh = useCallback(() => { api<Identity>('/api/identity').then(setIdentity).catch(() => setIdentity(null)) }, [])
  useEffect(refresh, [refresh])
  useEffect(() => {
    if (identity && window.location.pathname === '/sign-in') {
      const target = signInReturn(window.location.search, window.location.origin)
      if (target) window.location.assign(target)
    }
  }, [identity])
  if (identity === undefined) return <main className="p-8" role="status">Loading Keeplane…</main>
  if (identity === null) return <SignInPage onSignedIn={refresh} />
  if (identity.role === 'developer') return <DeveloperPage identity={identity} />
  return <BrowserRouter><Shell identity={identity}>
    <Suspense fallback={<p role="status">Loading…</p>}><Routes>
      <Route path="/" element={<ModelsPage />} />
      <Route path="/app/" element={<UsersPage />} />
      <Route path="/app/projects" element={<ProjectsPage />} />
      <Route path="/app/models" element={<ModelsPage />} />
      <Route path="/app/data-classes" element={<DataClassesPage />} />
      <Route path="/app/audit" element={<AuditPage />} />
      <Route path="/editions" element={<EditionsPage />} />
      <Route path="/users" element={<Navigate to="/app/" replace />} />
      <Route path="/models" element={<Navigate to="/app/models" replace />} />
      <Route path="/data-classes" element={<Navigate to="/app/data-classes" replace />} />
      <Route path="/audit" element={<Navigate to="/app/audit" replace />} />
      <Route path="/sign-in" element={<Navigate to="/app/" replace />} />
      <Route path="*" element={<p role="alert">This page does not exist.</p>} />
    </Routes></Suspense>
  </Shell></BrowserRouter>
}
