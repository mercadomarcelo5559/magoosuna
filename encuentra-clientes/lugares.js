// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-15: Cancún Centro, Malecón Tajamar y Playa del Carmen Centro (Quintana Roo).
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
    textQuery: 'dentista en Centro, Cancún, Quintana Roo',
    places: [
      lugar('smile-now-cancun', 'Smile Now Dental & Facial Care', 'Av. Tulum, Plaza San Francisco, local 303, SM 11, 77504 Cancún, Q.R.', '', 'https://www.smilenowdentalclinic.com/', { h: { ...LV([10, 19]), 6: [10, 14] } }),
      lugar('shtern-dental', 'Shtern Dental Clinic', 'C. Cielo 10, 77500 Cancún, Q.R.', '+52 998 321 4677', 'https://drmarkshtern.com/', { h: LV([10, 17]) }),
      lugar('ro-dental', 'Ro Dental', 'Plaza Corner Center, Av. Huayacán Mz 30, Col. Álamos, 77533 Cancún, Q.R.', '+52 998 187 6859', 'https://rodental.com.mx/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
      lugar('dentavida', 'Dentavida', 'Av. Kohunlich Mz 20, Lote 12, No. 1, Cancún, Q.R.', '', 'https://dentavida.com.mx/', { h: { ...LV([9, 18]), 6: [9, 14] } }),
      lugar('cancun-dental-center', 'Cancun Dental Center', 'Av. J. Rojo Gómez (Kabah), Plaza Royal Kabah, Porto Bello, Cancún, Q.R.', '+52 998 310 9866', '', { h: { ...LV([10, 20]), 6: [10, 15] } }),
      lugar('dentesco', 'Clínica Dental Dentesco', 'Supermanzana 3, Cancún, Q.R.', '+52 998 315 9579', '', { h: { ...LV([10, 20]), 6: [10, 13] } }),
    ],
  },
  {
    textQuery: 'dentista en Malecón Tajamar, Cancún, Quintana Roo',
    places: [
      lugar('cosmetica-dental-azuna', 'Cosmética Dental Azuna Cancún', 'Edificio Azuna, Av. Sayil esq. Av. Savignac, piso 9, Malecón Tajamar, 77500 Cancún, Q.R.', '+52 998 688 6732', 'https://cosmeticadentalcancun.com/'),
      lugar('lagoon-dental', 'Lagoon Dental Services', 'Azuna Professional Medical Center, piso 8, consultorio 805, Malecón Tajamar, Cancún, Q.R.', '', 'https://www.doctoralia.com.mx/clinicas/lagoon-dental-services'),
      lugar('new-look-dental', 'New Look Dental', 'Plaza Malecón Américas, Av. Bonampak SM 6, local 101A, 77503 Cancún, Q.R.', '+52 998 898 2273', 'https://newlookdentalcancun.com/', { h: { ...LV([8.5, 19]), 6: [8.5, 19] } }),
    ],
  },
  {
    textQuery: 'dentista en Playa del Carmen Centro, Solidaridad, Quintana Roo',
    places: [
      lugar('punto-dental', 'Punto Dental', 'Av. 15 entre calles 8 y 10, Centro, 77710 Playa del Carmen, Q.R.', '+52 984 105 1612', 'https://clinicapuntodental.mx/', { h: { ...LV([10, 20]), 6: [10, 14] } }),
      lugar('marfiles-dental', 'Marfiles · Emanuel Pérez Odontología', '5 Av. Nte. 10, Centro, 77710 Playa del Carmen, Q.R.', '+52 984 314 7676', 'https://marfilesdental.com/', { h: { ...LV([10, 18]), 6: [10, 14] } }),
      lugar('dentprax', 'DentPrax', 'Calle 12 Norte #230, entre Av. 15 y 20, Centro, Playa del Carmen, Q.R.', '+52 984 127 4806', 'https://dentprax.com/en', { h: LV([10, 19]) }),
      lugar('playa-smiles', 'Playa Smiles', '20 Avenida #179 esq. Calle 6, Centro, Playa del Carmen, Q.R.', '+52 984 803 4585', 'https://www.dentistplayadelcarmen.com/'),
      lugar('dpg-dental', 'DPG Dental Clinic', 'Av. 25 Norte esq. Calle 14 Norte, Gonzalo Guerrero, 77720 Playa del Carmen, Q.R.', '+52 984 100 5486', 'https://dpgdentalclinic.com/dentistas-playa-del-carmen/'),
      lugar('clinident-playa', 'CLINIDENT Odontología Integral', 'Av. Diagonal 85 Norte y Av. Benito Juárez, Ejidal, 77712 Playa del Carmen, Q.R.', '+52 984 859 3017', ''),
    ],
  },
];
