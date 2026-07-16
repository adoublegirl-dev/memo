<script>
  import { onMount } from 'svelte';
  import Shell from './components/Shell.svelte';
  import Overview from './routes/Overview.svelte';
  import Graph from './routes/Graph.svelte';
  import Memories from './routes/Memories.svelte';
  import Spaces from './routes/Spaces.svelte';
  import Persona from './routes/Persona.svelte';
  import Todos from './routes/Todos.svelte';
  import Governance from './routes/Governance.svelte';
  import { route, theme, setTheme } from './lib/stores.js';
  const routes = { '/': Overview, '/graph': Graph, '/memories': Memories, '/governance': Governance, '/spaces': Spaces, '/persona': Persona, '/todos': Todos };
  $: Page = routes[$route] || Overview;
  onMount(() => setTheme($theme));
</script>

<Shell>
  <svelte:component this={Page} />
</Shell>
