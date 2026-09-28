' Executa um robo sem abrir janela de console (usado pelo Agendador de Tarefas).
' Fechar a janela de console mata o robo (codigo 3221225786); por isso ela fica oculta.
' O navegador do PJe continua visivel quando o site exige.
'
' Uso: wscript.exe //B //NoLogo executar-oculto.vbs "<exe>" "<argumentos>" "<arquivo de log>"
Option Explicit
Dim args, exe, params, logFile, cmd, shell
Set args = WScript.Arguments
If args.Count < 3 Then WScript.Quit 2
exe = args(0)
params = args(1)
logFile = args(2)
' Resultado: cmd.exe /c ""EXE" PARAMS >> "LOG" 2>&1"
cmd = "cmd.exe /c """"" & exe & """ " & params & " >> """ & logFile & """ 2>&1"""
Set shell = CreateObject("WScript.Shell")
WScript.Quit shell.Run(cmd, 0, True)
