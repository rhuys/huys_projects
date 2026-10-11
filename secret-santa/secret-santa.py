import tkinter as tk
from tkinter import messagebox

def kies_naam(tekst, namen):
    """Choose a name from a list using a Listbox.
    Returns the index of the selected name, or -1 if canceled."""

    index = -1

    def choose():
        nonlocal index
        sel = listbox.curselection()
        if sel:  # if something is selected
            index = sel[0]
        dialog.destroy()

    def cancel():
        nonlocal index
        index = -1
        dialog.destroy()

    root = tk.Tk()
    root.withdraw()  # hide main window

    dialog = tk.Toplevel(root)
    dialog.title("Choose an option")
    dialog.grab_set()       # make it modal
    dialog.focus_force()
    dialog.resizable(False, False)

    tk.Label(dialog, text=tekst).pack(padx=10, pady=10)

    listbox = tk.Listbox(dialog, height=min(10, len(namen)))
    for name in namen:
        listbox.insert(tk.END, name)
    listbox.pack(padx=10, pady=5)
    listbox.selection_set(0)  # default selection

    # Buttons
    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=10)
    tk.Button(btn_frame, text="OK", command=choose).pack(side="left", padx=5)
    tk.Button(btn_frame, text="Cancel", command=cancel).pack(side="right", padx=5)

    # Handle window close
    dialog.protocol("WM_DELETE_WINDOW", cancel)

    dialog.wait_window()  # wait until dialog is closed
    root.destroy()

    return index

def ingave(namen):

    cadeau_aan = [-1, -1, -1, -1]

    for van_wie in range(len(namen)):

        tekst = "Dag %s, voor wie heb je een cadeautje gekocht?\nKlik CANCEL als je nog niks hebt gekozen" % namen[van_wie]

        voor_wie = kies_naam(tekst, namen)

        if voor_wie != -1:
            cadeau_aan[van_wie] = voor_wie

    return cadeau_aan

def tel_cadeaus(namen, cadeau_aan):

    meerdere_cadeaus = [i for i in range(len(namen)) if cadeau_aan.count(i) > 1]
    zichzelf_gekozen = [i for i in range(len(namen)) if cadeau_aan[i] == i]
    niet_gekozen = [i for i in range(len(namen)) if cadeau_aan[i] == -1]
    nog_geen_cadeau = [i for i in range(len(namen)) if i not in cadeau_aan]

    return meerdere_cadeaus, zichzelf_gekozen, niet_gekozen, nog_geen_cadeau

def check_cadeaus(namen, cadeau_aan, print_text = True):

    allemaal_ok = True
    meerdere_cadeaus, zichzelf_gekozen, niet_gekozen, nog_geen_cadeau = tel_cadeaus(namen, cadeau_aan)

    if len(meerdere_cadeaus) > 0:
        if print_text:
            print("Fout: iemand krijgt meerdere cadeaus")
        allemaal_ok = False
        
    if len(zichzelf_gekozen) > 0:
        if print_text:
            print("Fout: iemand heeft zichzelf gekozen")
        allemaal_ok = False

    if len(niet_gekozen) > 0:
        if print_text:
            print("Fout: iemand heeft nog niks gekozen")
        allemaal_ok = False

    if len(nog_geen_cadeau) > 0:
        if print_text:
            print("Fout: iemand krijgt nog geen cadeau")
        allemaal_ok = False

    return allemaal_ok

def voorstel_aanpasisng(namen, cadeau_aan):

    meerdere_cadeaus, zichzelf_gekozen, niet_gekozen, nog_geen_cadeau = tel_cadeaus(namen, cadeau_aan)

    if nog_geen_cadeau and niet_gekozen:
        cadeau_aan[niet_gekozen[0]] = nog_geen_cadeau[0]
    
    elif nog_geen_cadeau and zichzelf_gekozen:
        cadeau_aan[zichzelf_gekozen[0]] = nog_geen_cadeau[0]
    
    elif nog_geen_cadeau and meerdere_cadeaus:
        wie = cadeau_aan.index(meerdere_cadeaus[0])
        cadeau_aan[wie] = nog_geen_cadeau[0]

    elif len(zichzelf_gekozen)==1:
        #swith with next
        zichzelf = zichzelf_gekozen[0]
        andere = (zichzelf + 1) % len(namen)
        cadeau_aan[zichzelf] = cadeau_aan[andere]
        cadeau_aan[andere] = zichzelf

    elif len(zichzelf_gekozen)>=2:
        temp = cadeau_aan[zichzelf_gekozen[0]]
        cadeau_aan[zichzelf_gekozen[0]] = cadeau_aan[zichzelf_gekozen[1]]
        cadeau_aan[zichzelf_gekozen[1]] = temp

    return cadeau_aan

namen = ["Roeland", "Sara", "Casper", "Fien"]

root = tk.Tk()
root.withdraw()  # Hide the main window

cadeau_aan = ingave(namen)

# Testcases:
#cadeau_aan = [0, 2, 3, 0]  # 0 heeft zichzelf gekozen
#cadeau_aan = [-1, 2, 3, 0]  # 0 heeft niet gekozen
#cadeau_aan = [1, 2, 0, 0]  # 0 krijgt meerdere cadeaus
#cadeau_aan = [0, 2, 1, 3]  # twee hebben zichzelf gekozen
#cadeau_aan = [-1, 2, 3, 1] # 0 heeft niet gekozen, 1 krijgt geen cadeau
#cadeau_aan = [1, 2, 3, 0]  # OK
#print(cadeau_aan)

if check_cadeaus(namen, cadeau_aan):
    messagebox.showinfo("", "Alles is in orde!")

else:
    cadeau_aan_aangepast = cadeau_aan.copy()

    while not check_cadeaus(namen, cadeau_aan_aangepast, print_text = False):
        cadeau_aan_aangepast = voorstel_aanpasisng(namen, cadeau_aan_aangepast)

    for i in range(len(namen)):
        if cadeau_aan[i] != cadeau_aan_aangepast[i]:

            messagebox.showinfo("", "Ben jij %s?  Ben je alleen?  Klik dan op OK.  " % namen[i])

            if cadeau_aan[i] == -1:
                msg = "Hallo %s, je mag een cadeautje gaan kopen voor %s" % (namen[i], namen[cadeau_aan_aangepast[i]])
            else:
                msg = "Hallo %s, in plaats aan %s, mag je nu een cadeautje gaan kopen voor %s" % (namen[i], namen[cadeau_aan[i]], namen[cadeau_aan_aangepast[i]])

            messagebox.showinfo("", msg)


