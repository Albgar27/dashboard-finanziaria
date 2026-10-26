"""Voci di bilancio usate dalla piattaforma e corrispondenza con la tassonomia XBRL italiana (itcc-ci 2018-11-04).

Ogni voce ha: chiave interna, etichetta, sezione, elementi XBRL in ordine di preferenza (vince il primo
presente) e, in alternativa, elementi da sommare quando il totale non è nel file (bilanci abbreviati o
voci senza totale). I nomi degli elementi sono quelli del modello ufficiale XBRL_NI_GENERATOR.
"""
from __future__ import annotations

import re

# (chiave, etichetta, sezione, elementi preferiti, elementi da sommare o regex, accetta contesti con dimensioni)
VOCI = [
    # ---- Stato patrimoniale: attivo
    ("immobilizzazioni_immateriali", "Immobilizzazioni immateriali", "attivo", ["TotaleImmobilizzazioniImmateriali"], None, False),
    ("immobilizzazioni_materiali", "Immobilizzazioni materiali", "attivo", ["TotaleImmobilizzazioniMateriali"], None, False),
    ("immobilizzazioni_finanziarie", "Immobilizzazioni finanziarie", "attivo", ["TotaleImmobilizzazioniFinanziarie"], None, False),
    ("immobilizzazioni", "Totale immobilizzazioni (B)", "attivo", ["TotaleImmobilizzazioni"], None, False),
    ("rimanenze", "Rimanenze (C.I)", "attivo", ["TotaleRimanenze"], None, False),
    ("crediti_clienti", "Crediti verso clienti", "attivo", ["CreditiVersoClientiTotaleCreditiVersoClienti"], None, False),
    ("crediti", "Totale crediti (C.II)", "attivo", ["TotaleCrediti"], None, False),
    ("crediti_oltre", "di cui esigibili oltre l'esercizio", "attivo", ["CreditiEsigibiliOltreEsercizioSuccessivo"],
     re.compile(r"^Crediti.+EsigibiliOltreEsercizioSuccessivo$"), False),
    ("attivita_finanziarie", "Attività finanziarie non immobilizzate (C.III)", "attivo",
     ["TotaleAttivitaFinanziarieNonCostituisconoImmobilizzazioni"], None, False),
    ("liquidita", "Disponibilità liquide (C.IV)", "attivo", ["TotaleDisponibilitaLiquide"], None, False),
    ("attivo_circolante", "Totale attivo circolante (C)", "attivo", ["TotaleAttivoCircolante"], None, False),
    ("totale_attivo", "Totale attivo", "attivo", ["TotaleAttivo"], None, False),
    # ---- Stato patrimoniale: passivo
    ("capitale", "Capitale sociale", "passivo", ["PatrimonioNettoCapitale"], None, False),
    ("patrimonio_netto", "Totale patrimonio netto (A)", "passivo", ["TotalePatrimonioNetto"], None, False),
    ("fondi_rischi", "Fondi per rischi e oneri (B)", "passivo", ["TotaleFondiRischiOneri"], None, False),
    ("tfr", "Fondo TFR (C)", "passivo", ["TrattamentoFineRapportoLavoroSubordinato"], None, False),
    ("debiti", "Totale debiti (D)", "passivo", ["TotaleDebiti"], None, False),
    ("debiti_entro", "Debiti esigibili entro l'esercizio", "passivo", ["DebitiEsigibiliEntroEsercizioSuccessivo"],
     re.compile(r"^Debiti.+EsigibiliEntroEsercizioSuccessivo$"), False),
    ("debiti_oltre", "Debiti esigibili oltre l'esercizio", "passivo", ["DebitiEsigibiliOltreEsercizioSuccessivo"],
     re.compile(r"^Debiti.+EsigibiliOltreEsercizioSuccessivo$"), False),
    ("debiti_banche", "Debiti verso banche", "passivo", ["DebitiDebitiVersoBancheTotaleDebitiVersoBanche"], None, False),
    ("debiti_banche_entro", "di cui verso banche entro l'esercizio", "passivo",
     ["DebitiDebitiVersoBancheEsigibiliEntroEsercizioSuccessivo"], None, False),
    ("debiti_altri_finanziatori", "Debiti verso altri finanziatori", "passivo",
     ["DebitiDebitiVersoAltriFinanziatoriTotaleDebitiVersoAltriFinanziatori"], None, False),
    ("obbligazioni", "Obbligazioni (anche convertibili)", "passivo", [],
     ["DebitiObbligazioniTotaleObbligazioni", "DebitiObbligazioniConvertibiliTotaleObbligazioniConvertibili"], False),
    ("debiti_soci", "Debiti verso soci per finanziamenti", "passivo",
     ["DebitiDebitiVersoSociFinanziamentiTotaleDebitiVersoSociFinanziamenti"], None, False),
    ("debiti_fornitori", "Debiti verso fornitori", "passivo", ["DebitiDebitiVersoFornitoriTotaleDebitiVersoFornitori"], None, False),
    ("debiti_tributari", "Debiti tributari", "passivo", ["DebitiDebitiTributariTotaleDebitiTributari"], None, False),
    ("debiti_previdenziali", "Debiti verso istituti previdenziali", "passivo",
     ["DebitiDebitiVersoIstitutiPrevidenzaSicurezzaSocialeTotaleDebitiVersoIstitutiPrevidenzaSicurezzaSociale"], None, False),
    ("totale_passivo", "Totale passivo", "passivo", ["TotalePassivo"], None, False),
    # ---- Conto economico
    ("ricavi", "Ricavi delle vendite (A1)", "ce", ["ValoreProduzioneRicaviVenditePrestazioni"], None, False),
    ("valore_produzione", "Valore della produzione (A)", "ce", ["TotaleValoreProduzione"], None, False),
    ("materie", "Materie prime e merci (B6)", "ce", ["CostiProduzioneMateriePrimeSussidiarieConsumoMerci"], None, False),
    ("servizi", "Servizi (B7)", "ce", ["CostiProduzioneServizi"], None, False),
    ("godimento_beni_terzi", "Godimento beni di terzi (B8)", "ce", ["CostiProduzioneGodimentoBeniTerzi"], None, False),
    ("costo_personale", "Costo del personale (B9)", "ce", ["CostiProduzionePersonaleTotaleCostiPersonale"], None, False),
    ("salari", "Salari e stipendi (B9a)", "ce", ["CostiProduzionePersonaleSalariStipendi"], None, False),
    ("accantonamento_tfr", "Accantonamento TFR (B9c)", "ce", ["CostiProduzionePersonaleTrattamentoFineRapporto"], None, False),
    ("ammortamenti", "Ammortamenti e svalutazioni (B10)", "ce",
     ["CostiProduzioneAmmortamentiSvalutazioniTotaleAmmortamentiSvalutazioni"],
     ["CostiProduzioneAmmortamentiSvalutazioniAmmortamentoImmobilizzazioniImmateriali",
      "CostiProduzioneAmmortamentiSvalutazioniAmmortamentoImmobilizzazioniMateriali",
      "CostiProduzioneAmmortamentiSvalutazioniAltreSvalutazioniImmobilizzazioni",
      "CostiProduzioneAmmortamentiSvalutazioniAmmortamentoImmobilizzazioniImmaterialiMaterialiAltreSvalutazioniImmobilizzazioni",
      "CostiProduzioneAmmortamentiSvalutazioniSvalutazioniCreditiCompresiAttivoCircolanteDisponibilitaLiquide"], False),
    ("accantonamenti", "Accantonamenti (B12 + B13)", "ce", [],
     ["CostiProduzioneAccantonamentiRischi", "CostiProduzioneAltriAccantonamenti"], False),
    ("costi_produzione", "Costi della produzione (B)", "ce", ["TotaleCostiProduzione"], None, False),
    ("ebit", "Differenza A − B (risultato operativo)", "ce", ["DifferenzaValoreCostiProduzione"], None, False),
    ("oneri_finanziari", "Interessi e oneri finanziari (C17)", "ce",
     ["ProventiOneriFinanziariInteressiAltriOneriFinanziariTotaleInteressiAltriOneriFinanziari"], None, False),
    ("gestione_finanziaria", "Saldo proventi e oneri finanziari (C)", "ce", ["TotaleProventiOneriFinanziari"], None, False),
    ("risultato_ante_imposte", "Risultato prima delle imposte", "ce", ["RisultatoPrimaImposte"], None, False),
    ("imposte", "Imposte sul reddito (20)", "ce",
     ["ImposteRedditoEsercizioCorrentiDifferiteAnticipateTotaleImposteRedditoEsercizioCorrentiDifferiteAnticipate"], None, False),
    ("utile", "Utile (perdita) dell'esercizio", "ce", ["UtilePerditaEsercizio"], None, False),
    # ---- Nota integrativa (spesso in tabelle con dimensioni)
    ("dipendenti", "Numero medio dipendenti", "nota", ["TotaleDipendentiNumeroMedio"], None, True),
    ("compensi_amministratori", "Compensi amministratori", "nota", ["AmministratoriCompensi"], None, True),
]

CHIAVI = [v[0] for v in VOCI]
ETICHETTE = {v[0]: v[1] for v in VOCI}
SEZIONI = {"attivo": "Stato patrimoniale – Attivo", "passivo": "Stato patrimoniale – Passivo",
           "ce": "Conto economico", "nota": "Nota integrativa"}


def elenco_per_interfaccia():
    return [{"chiave": k, "etichetta": e, "sezione": s} for k, e, s, *_ in VOCI]
