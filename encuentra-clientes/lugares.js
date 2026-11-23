// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-23: Centro (Ciudad Juárez), Centro (Cuernavaca) y Centro (Pachuca).
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
    textQuery: 'dentista en Juárez Centro, Ciudad Juárez, Chihuahua',
    places: [
      lugar('torres-cirujano-dentista', 'Torres Cirujano Dentista', 'Av. Lerdo 388 Nte., Centro, Ciudad Juárez, Chih.', '+52 656 612 4604', '', { h: { ...LV([9, 18]), 6: [9, 18] } }),
      lugar('llanas-dental', 'Llanas Dental', 'Av. Hermanos Escobar 2075, Col. Hidalgo, 32300 Ciudad Juárez, Chih.', '+52 656 703 9013', 'https://llanasdental.com/', { h: { ...LV([9, 18]), 6: [9, 14] } }),
      lugar('dental-del-centro-cdj', 'Dental Del Centro', 'Av. de las Torres 2751, Lote Bravo, Ciudad Juárez, Chih.', '+52 656 623 7497', '', { h: { ...LV([9, 17]), 6: [9, 17] } }),
      lugar('c-dental-juarez', 'C Dental', 'Paseo de la Victoria 2736, Jardines del Bosque, Ciudad Juárez, Chih.', '+52 656 814 5376', 'https://www.cdentaljuarez.com/', { h: { ...LV([9, 19.5]), 6: [9, 14] } }),
      lugar('clinica-mas-dental', 'Clínica Más Dental', 'Ramón Rayón 9951, Parajes del Sol, Ciudad Juárez, Chih.', '+52 656 681 0159', 'http://www.clinicamasdentaljuarez.com/', { h: { ...LV([9.5, 18]), 6: [10, 14] } }),
      lugar('be-dental-juarez', 'Be Dental Juárez', 'CP 32310, Ciudad Juárez, Chih.', '+52 656 440 5857', '', { h: { ...LV([10, 18]), 6: [10, 15] } }),
    ],
  },
  {
    textQuery: 'dentista en Cuernavaca Centro, Cuernavaca, Morelos',
    places: [
      lugar('healteeth', 'Healteeth Dental Center', 'Plaza Esmeralda, Av. Morelos 178, D-3, Centro, Cuernavaca, Mor.', '+52 777 310 3654', ''),
      lugar('dental-mango', 'Clínica Dental Mango', 'Ricardo Linares #10, 1er piso, Centro, Cuernavaca, Mor.', '+52 777 318 9141', ''),
      lugar('estudio-134', 'Estudio 134 Clínica Dental', 'Álvaro Obregón 134, Centro, Cuernavaca, Mor.', '+52 777 318 3005', ''),
      lugar('dental-spekter', 'Clínica Dental Spekter', 'Chapultepec, Cuernavaca, Mor.', '+52 777 159 8684', 'https://dentalspekter.com/dentista-en-cuernavaca', { h: { ...LV([10, 19]), 6: [10, 17] } }),
      lugar('wesmile-cuernavaca', 'Clínica Dental Cuernavaca (WeSmile)', 'Av. Alta Tensión 18, local 208, Cantarranas, Cuernavaca, Mor.', '+52 777 244 6560', 'https://www.clinicadentalcuernavaca.com/', { h: { ...LV([8, 20]), 6: [8, 14] } }),
      lugar('la-clinica-dental-cuernavaca', 'La Clínica Dental Cuernavaca', 'Av. Río Mayo 1001, Vista Hermosa, Cuernavaca, Mor.', '+52 777 454 0185', 'https://laclinicadental.com.mx/sobre-nosotros/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
    ],
  },
  {
    textQuery: 'dentista en Pachuca Centro, Pachuca, Hidalgo',
    places: [
      lugar('rehabilitacion-bucodental-pachuca', 'Centro de Rehabilitación Bucodental', 'Av. Benito Juárez 1221, Centro, 42080 Pachuca, Hgo.', '+52 771 713 2691', ''),
      lugar('gardini-clinic', 'Gardini Clinic', 'Av. Revolución 1104, Pachuca, Hgo.', '', 'https://gardiniclinic.com/'),
      lugar('vivadental-pachuca', 'Vivadental', 'Reyna de los Mártires 938, Pachuca, Hgo.', '+52 771 203 5540', ''),
      lugar('abba-medica-dental', 'ABBA Médica Dental', 'Río Amajac 103, Fracc. Las Terrazas, Pachuca, Hgo.', '+52 771 473 5289', 'https://www.abbaclinicadental.com/', { h: { ...LV([8, 19]), 6: [8, 14] } }),
      lugar('alfa-cem', 'Clínica Dental ALFA-CEM', 'Pachuca, Hgo.', '+52 771 119 8688', '', { h: LV([9, 20]) }),
    ],
  },
];
