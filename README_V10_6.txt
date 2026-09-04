MENORCA BUS V10.6 - RECUPERA PARADAS

Problema corregido:
V10.5 permitía origen/destino desde topología, pero /api/origin-stops dependía
de matrices horarias. Si la sincronización general daba 0 bloques, no salía
ninguna parada.

V10.6:
- mantiene origen/destino de la topología;
- las paradas y horas siguen saliendo EXCLUSIVAMENTE de matrices reales;
- L01 usa como garantía el parser de V9.4 que ya funcionó;
- la sincronización se considera inválida si L01 queda sin bloques;
- una línea sin matriz no borra ni rompe las matrices de otras líneas.

Diagnóstico después de arrancar:
http://127.0.0.1:5055/api/debug-blocks

L01 debe mostrar blocks > 0.

Luego prueba el flujo normal.

Puerto fijo: 5055.
