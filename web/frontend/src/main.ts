import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap-icons/font/bootstrap-icons.css';
import App from './App.svelte';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

const app = new App({ target: document.getElementById('app')! });
export default app;
