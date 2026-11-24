// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-24: Americana, Chapalita (Guadalajara) y Puerta de Hierro (Zapopan).
// Una respuesta por zona, igual que "Arma las búsquedas" -> "Busca en Google Maps".
// Calificaciones: de agregadores (no de Google). Reseñas: no se obtuvieron textos, se dejan vacías (no se inventan).
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
// h: { 1: [9, 19], ..., 6: [10, 14] }  (0 = domingo)
const hm = (x) => ({ hour: Math.floor(x), minute: Math.round((x % 1) * 60) });
const txt = (x) => `${Math.floor(x)}:${String(Math.round((x % 1) * 60)).padStart(2, '0')}`;
const rangos = (v) => (Array.isArray(v[0]) ? v : [v]);
const horario = (h) => {
  if (!h) return undefined;
  const periods = Object.entries(h).flatMap(([d, v]) => rangos(v).map(([a, c]) => ({ open: { day: +d, ...hm(a) }, close: { day: +d, ...hm(c) } })));
  const orden = [1, 2, 3, 4, 5, 6, 0];
  const weekdayDescriptions = orden.map((d) => `${DIAS[d]}: ${h[d] ? rangos(h[d]).map(([a, c]) => `${txt(a)}–${txt(c)}`).join(', ') : 'Cerrado'}`);
  return { periods, weekdayDescriptions };
};
const semana = (a, c, sab, dom) => {
  const h = { 1: [a, c], 2: [a, c], 3: [a, c], 4: [a, c], 5: [a, c] };
  if (sab) h[6] = sab;
  if (dom) h[0] = dom;
  return h;
};
const maps = (n, d) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${n}, ${d}`)}`;
const lugar = (id, nombre, direccion, tel, web, extra = {}) => ({
  id: `web-${id}`,
  displayName: { text: nombre },
  formattedAddress: direccion,
  internationalPhoneNumber: tel || undefined,
  websiteUri: web || undefined,
  googleMapsUri: maps(nombre, direccion),
  rating: extra.rating,
  userRatingCount: extra.total,
  regularOpeningHours: horario(extra.h),
  reviews: [],
  businessStatus: 'OPERATIONAL',
});

const LV = (r) => ({ 1: r, 2: r, 3: r, 4: r, 5: r });
module.exports = [
  {
    textQuery: 'dentista en Americana, Guadalajara, Jalisco',
    places: [
      lugar('dental-glow-gdl', 'Dental Glow', 'José Guadalupe Montenegro 2072, Americana, Guadalajara, Jal.', '+52 33 4697 6630', 'https://www.dentistagdl.com/en'),
      lugar('hector-ochoa', 'Dr. Héctor Ochoa Velázquez', 'C. Bruselas 158, Americana, Guadalajara, Jal.', '+52 33 3825 6860', 'https://www.doctoranytime.mx/d/dentista/hector-ochoa-velazquez'),
      lugar('dental-coy-gdl', 'Dental Coy GDL', 'Colonia Americana, Guadalajara, Jal.', '+52 33 1895 9623', 'https://www.facebook.com/p/Dental-Coy-GDL-100063562749140/'),
      lugar('consultorio-hidalgo-1362', 'Consultorio Dental Av. Hidalgo 1362', 'Av. Hidalgo 1362, Americana, Guadalajara, Jal.', '+52 33 3826 0040', ''),
    ],
  },
  {
    textQuery: 'dentista en Chapalita, Guadalajara, Jalisco',
    places: [
      lugar('deo-clinic', 'Deo Clinic', 'Av. Guadalupe 618, Chapalita, 44500 Guadalajara, Jal.', '+52 33 1178 4981', 'https://www.doctoralia.com.mx/clinicas/deo-clinic', { h: { 1: [9.5, 14.5], 2: [9.5, 14.5], 3: [9.5, 20], 4: [9.5, 14.5], 5: [9.5, 14.5], 6: [9.5, 14] } }),
      lugar('gineco-dental-chapalita', 'Gineco Dental Chapalita', 'Ermita 1428, Chapalita Sur, 45030 Zapopan, Jal.', '+52 33 3647 6868', '', { h: { ...LV([9, 19]), 6: [9, 14] } }),
      lugar('denz-dental', 'Denz', 'Av. Tonantzin 1030, Chapalita, 45040 Guadalajara, Jal.', '+52 33 3304 4085', 'https://denzdental.com/', { h: { ...LV([10, 20]), 6: [10, 14] } }),
      lugar('dental-chapalita', 'Dental Chapalita', '12 de Diciembre 1048, int. 102, Chapalita, Guadalajara, Jal.', '+52 33 3121 4599', 'http://www.dentalchapalita.com.mx/'),
    ],
  },
  {
    textQuery: 'dentista en Puerta de Hierro, Zapopan, Jalisco',
    places: [
      lugar('coph', 'Centro Odontológico Puerta de Hierro', 'Av. Empresarios 150, piso 7, consultorio 703, Puerta de Hierro, Zapopan, Jal.', '+52 33 1460 3826', 'https://www.facebook.com/COPHodontologia/'),
      lugar('dentalia-andares', 'dentalia Andares', 'Blvd. Puerta de Hierro 4965, 45116 Zapopan, Jal.', '+52 33 3611 1725', 'https://www.dentalia.com/dentistas/zapopan'),
      lugar('dra-daniela-garcia', 'Dra. Daniela García · Odontología Estética', 'Empresarios 150, Torre Elite, piso 19, Hospital Puerta de Hierro, Zapopan, Jal.', '+52 33 3945 9872', 'https://www.dradanielagrc.com/', { h: LV([16, 20]) }),
    ],
  },
];
