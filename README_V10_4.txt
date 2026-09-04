MENORCA BUS V10.4

CORRECCIÓN:
- El selector de ORIGEN ya no depende de topology_edges.
- Origen se obtiene de todas las poblaciones detectadas en:
  1) matrices horarias,
  2) recorridos sincronizados,
  3) catálogo base de Menorca sólo si lo anterior está vacío.
- DESTINO sigue siendo estricto: sólo aparece si se puede demostrar que es viable.

Así evitamos que el origen quede vacío por un fallo parcial del parser,
sin volver a permitir destinos imposibles.

Puerto fijo:
http://127.0.0.1:5055/
