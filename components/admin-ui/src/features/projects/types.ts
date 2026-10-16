export type ProjectClass = { id: string; name: string }
export type Project = {
  id: string
  name: string
  initialized: boolean
  users: { id: string; username: string }[]
  data_class?: ProjectClass | null
}
export type ProjectPage = {
  projects: Project[]; classes_enabled: boolean; page: number
  page_size: number; total: number; has_more: boolean
}
