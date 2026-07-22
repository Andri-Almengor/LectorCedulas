using System;
using System.Drawing;
using System.Windows.Forms;

public class DmsQaForm : Form {
    public DmsQaForm() {
        Text = "DMS QA WinForms Form";
        Width = 520; Height = 280;
        string[] names = {"Primer Apellido", "Nombre", "Cedula", "Fecha de Nacimiento"};
        for (int i = 0; i < names.Length; i++) {
            Controls.Add(new Label {Text = names[i], Left = 15, Top = 25 + i * 45, Width = 160});
            Controls.Add(new TextBox {Name = "field" + i, Left = 180, Top = 20 + i * 45, Width = 280, TabIndex = i});
        }
    }
    [STAThread] public static void Main() {
        Application.EnableVisualStyles();
        Application.Run(new DmsQaForm());
    }
}
