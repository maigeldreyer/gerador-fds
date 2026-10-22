import { ViaExposicao, classificarToxicidadeAguda } from '../js/motorToxicidadeAguda.js';
import { classificarCorrosaoIrritacaoPele, classificarLesaoOcular } from '../js/motorCorrosaoIrritacao.js';

const casos = {};

const ingsA = [
  { nome: "A", cas: "1", concentracao: 2.5, eta: 100, categoria: null, sem_toxicidade_aguda: false },
  { nome: "B", cas: "2", concentracao: 1.5, eta: null, categoria: null, sem_toxicidade_aguda: false },
];
casos.tox_eta_desconhecida = classificarToxicidadeAguda(ingsA, ViaExposicao.DERMICA);

const mkPO = (o) => ({ cas: null, categoria_pele: null, categoria_olhos: null, ph: null, acido_ou_base_forte: false, nao_apto_aditividade: false, relevante_abaixo_1pct: false, sem_perigo_pele_olhos: false, ...o });

const ingsB = [
  mkPO({ nome: "Acido", cas: "3", concentracao: 2.0, ph: 1.0, acido_ou_base_forte: true }),
  mkPO({ nome: "Agua", cas: "4", concentracao: 98.0, sem_perigo_pele_olhos: true }),
];
casos.pele_acido_forte = classificarCorrosaoIrritacaoPele(ingsB);
casos.olhos_acido_forte = classificarLesaoOcular(ingsB);

const ingsC = [
  mkPO({ nome: "Corrosivo", cas: "5", concentracao: 1.5, categoria_pele: "1B", categoria_olhos: "1", nao_apto_aditividade: true }),
  mkPO({ nome: "Agua", cas: "6", concentracao: 98.5, sem_perigo_pele_olhos: true }),
];
casos.pele_nao_apto = classificarCorrosaoIrritacaoPele(ingsC);
casos.olhos_nao_apto = classificarLesaoOcular(ingsC);

const ingsD = [
  mkPO({ nome: "Forte1A", cas: "7", concentracao: 6.0, categoria_pele: "1A", categoria_olhos: "1" }),
  mkPO({ nome: "Leve3", cas: "8", concentracao: 15.0, categoria_pele: "3", categoria_olhos: "2B" }),
];
casos.pele_1a_misto = classificarCorrosaoIrritacaoPele(ingsD);
casos.olhos_1a_misto = classificarLesaoOcular(ingsD);

console.log(JSON.stringify(casos, null, 2));
