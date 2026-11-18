// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-18: Metepec, Satélite e Interlomas (Estado de México).
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
    textQuery: 'dentista en Metepec Centro, Metepec, Estado de México',
    places: [
      lugar('novodent', 'Novodent Clínica Dental Integral', 'Blvd. Toluca-Metepec 601 Nte., lote 8, Plaza San Juan, La Purísima, 52169 Metepec, Méx.', '+52 722 917 0170', 'https://www.novodent.mx/clinica-dental/', { h: { 1: [10, 19], 2: [10, 20], 3: [10, 20], 4: [10, 20], 5: [10, 16], 6: [8, 15] } }),
      lugar('dental-care-metepec', 'Dental Care Metepec', 'Guadalupe Victoria 1330L, La Purísima, Metepec, Méx.', '+52 722 107 6469', ''),
      lugar('nishikawa', 'Nishikawa Clínica Dental', 'Calle Leona Vicario 204, Coaxustenco, 52140 Metepec, Méx.', '+52 722 270 2614', 'https://www.clinicadentalnishikawa.com/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
      lugar('dodental-tecnologico', 'Dodental Tecnológico', 'Av. Tecnológico 733, Agrícola Bellavista, 52172 Metepec, Méx.', '+52 722 649 7576', 'https://dodental.mx/'),
      lugar('dental-flores-metepec', 'Dental Flores', '16 de Septiembre 611-A, 52175 Metepec, Méx.', '+52 722 180 1273', 'https://dental-flores.ueniweb.com/', { h: { ...LV([9, 20]), 6: [9, 15] } }),
      lugar('white-dental-metepec', 'White Dental Metepec', 'Calle Josefa Ortiz de Domínguez 538, Metepec, Méx.', '+52 722 347 6500', 'https://whitedentalmetepec.com/'),
      lugar('stetic-dental-design', 'Stetic Dental Design', 'H. Ayuntamiento 203-C, La Municipal, 52168 Metepec, Méx.', '+52 722 459 9669', '', { h: { ...LV([8, 17]), 6: [8, 13.5] } }),
      lugar('4u-dental-studio', '4U Dental Studio', 'Torre de Especialidades Hospital Médica MIA, 3er piso, consultorio 319, Metepec, Méx.', '+52 722 622 2462', 'https://4udentalstudio.com/', { h: { ...LV([9, 18]), 6: [9, 15] } }),
    ],
  },
  {
    textQuery: 'dentista en Satélite, Naucalpan, Estado de México',
    places: [
      lugar('la-clinica-dental-satelite', 'La Clínica Dental Satélite', 'Manuel E. Izaguirre #2, Ciudad Satélite, 53100 Naucalpan, Méx.', '+52 55 9435 7143', 'https://laclinicasatelite.mx/'),
      lugar('dentalia-satelite', 'dentalia Satélite', 'Ciudad Satélite, Naucalpan, Méx.', '+52 55 1102 3864', 'https://www.dentalia.com/clinica/dentalia-satelite'),
      lugar('consultorio-dental-satelite', 'Consultorio Dental Satélite', 'Circuito Historiadores S-44, local 3, Ciudad Satélite, Naucalpan, Méx.', '', 'http://consultoriodentalsatelite.com.mx/'),
    ],
  },
  {
    textQuery: 'dentista en Interlomas, Huixquilucan, Estado de México',
    places: [
      lugar('la-clinica-dental-interlomas', 'La Clínica Dental Interlomas', 'Corporativo Palmas Uno, Blvd. Palmas Hills 1, piso 5, Valle de las Palmas, 52787 Huixquilucan, Méx.', '+52 55 7583 9507', '', { h: { ...LV([9, 20]), 6: [9, 16] } }),
      lugar('smile-works-interlomas', 'Smile Works Interlomas', 'Corporativo Terraz, Pasaje Interlomas 39, int. 301, 52787 Huixquilucan, Méx.', '+52 55 2685 4906', 'https://www.smileworksinterlomas.com/', { h: { ...LV([10, 19]), 6: [10, 13] } }),
      lugar('grupo-odontologico-lomas', 'Grupo Odontológico Lomas (Interlomas)', 'Blvd. Interlomas 24-705, Lomas Anáhuac, Huixquilucan, Méx.', '+52 55 5989 9451', 'https://www.grupodontologicolomas.com/'),
      lugar('zendo-dental', 'Zendo Dental Interlomas', 'Av. Jesús del Monte 37, 52764 Huixquilucan, Méx.', '+52 55 5247 7065', 'https://zendodental.com.mx/'),
      lugar('dentalia-magnocentro', 'dentalia Magnocentro Interlomas', 'Blvd. Magnocentro 35, 52760 Huixquilucan, Méx.', '+52 800 003 3682', 'https://www.dentalia.com/'),
      lugar('estetica-dental-interlomas-cabanas', 'Centro de Estética Dental Interlomas · Dr. Héctor Cabañas', 'Blvd. Interlomas 14-110, Huixquilucan, Méx.', '+52 55 5291 8176', ''),
    ],
  },
];
