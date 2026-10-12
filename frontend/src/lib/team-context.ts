/** An explicit URL project belongs to this tab. Never change a global auth cookie. */
export function selectedProject(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("project");
}

export function projectApiUrl(url: string): string {
  const project = selectedProject();
  if (!project) return url;
  const hashIndex = url.indexOf("#");
  const base = hashIndex === -1 ? url : url.slice(0, hashIndex);
  const fragment = hashIndex === -1 ? "" : url.slice(hashIndex);
  return `${base}${base.includes("?") ? "&" : "?"}workspace=${encodeURIComponent(project)}${fragment}`;
}

export function projectHref(path: string, project = selectedProject()): string {
  if (!project) return path;
  return `${path}${path.includes("?") ? "&" : "?"}project=${encodeURIComponent(project)}`;
}

export function switchProject(id: string | null, pathname = "/vault") {
  // A full navigation fences all outstanding requests and component caches.
  window.location.assign(projectHref(pathname, id));
}
