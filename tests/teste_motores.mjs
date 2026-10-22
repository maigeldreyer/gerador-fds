import { ViaExposicao, classificarToxicidadeAguda } from '../js/motorToxicidadeAguda.js';
import { classificarCorrosaoIrritacaoPele, classificarLesaoOcular } from '../js/motorCorrosaoIrritacao.js';

// Caso 1: mesmo exemplo do motor_toxicidade_aguda.py
const ingredientesOral = [
  { nome: "Lauril éter sulfato de sódio", cas: "68891-38-3", concentracao: 5.4, eta: 1288, categoria: null, sem_toxicidade_aguda: false },
  { nome: "Cloreto de sódio", cas: "7647-14-5", concentracao: 1.0, eta: null, categoria: null, sem_toxicidade_aguda: true },
  { nome: "Conservante X", cas: "0000-00-0", concentracao: 0.3, eta: null, categoria: 4, sem_toxicidade_aguda: false },
  { nome: "Água", cas: "7732-18-5", concentracao: 93.3, eta: null, categoria: null, sem_toxicidade_aguda: true },
];
console.log("=== Toxicidade aguda (oral) ===");
console.log(JSON.stringify(classificarToxicidadeAguda(ingredientesOral, ViaExposicao.ORAL), null, 2));

// Caso 2: mesmo exemplo do motor_corrosao_irritacao.py
const ingredientes = [
  { nome: "Tensoativo X", cas: "0001-01-1", concentracao: 8.0, categoria_pele: "2", categoria_olhos: "2A", ph: null, acido_ou_base_forte: false, nao_apto_aditividade: false, relevante_abaixo_1pct: false, sem_perigo_pele_olhos: false },
  { nome: "Conservante corrosivo Y", cas: "0002-02-2", concentracao: 0.5, categoria_pele: "1B", categoria_olhos: "1", ph: null, acido_ou_base_forte: false, nao_apto_aditividade: false, relevante_abaixo_1pct: false, sem_perigo_pele_olhos: false },
  { nome: "Água", cas: "7732-18-5", concentracao: 91.5, categoria_pele: null, categoria_olhos: null, ph: null, acido_ou_base_forte: false, nao_apto_aditividade: false, relevante_abaixo_1pct: false, sem_perigo_pele_olhos: true },
];
console.log("\n=== Pele ===");
console.log(JSON.stringify(classificarCorrosaoIrritacaoPele(ingredientes), null, 2));
console.log("\n=== Olhos ===");
console.log(JSON.stringify(classificarLesaoOcular(ingredientes), null, 2));
