import { mount } from 'svelte';
import App from './App.svelte';
import './styles/theme.css';
import './styles/base.css';
import './styles/components.css';
import './styles/motion.css';

const app = mount(App, { target: document.getElementById('app') });
export default app;
