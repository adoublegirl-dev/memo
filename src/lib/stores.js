import { writable } from 'svelte/store';

export const route = writable(location.hash.replace('#', '') || '/');
export const theme = writable(localStorage.getItem('memo-theme') || 'light');
export const activeSpace = writable(null);

export function navigate(path) {
  location.hash = path;
  route.set(path);
}

export function initRouter() {
  window.addEventListener('hashchange', () => route.set(location.hash.replace('#', '') || '/'));
}

export function setTheme(next) {
  document.documentElement.dataset.theme = next;
  localStorage.setItem('memo-theme', next);
  theme.set(next);
}
