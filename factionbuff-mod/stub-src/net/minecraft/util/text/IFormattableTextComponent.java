package net.minecraft.util.text;

/**
 * Compile-only stub. javac chokes on the real srg jar's class file for this
 * type ("bad RuntimeInvisibleParameterAnnotations attribute") even though
 * the JVM loads it fine at runtime, so we stub just enough of its shape to
 * compile against. Method names (func_230529_a_ = append(ITextComponent),
 * func_240699_a_ = mergeStyle(TextFormatting)) were verified against the
 * real SRG-named class file's own declared members, and cross-checked
 * against FTB Essentials' compiled bytecode which calls both successfully
 * in this exact server environment. Never bundle this stub into the mod jar.
 */
public interface IFormattableTextComponent extends ITextComponent {
    IFormattableTextComponent func_230529_a_(ITextComponent sibling);

    IFormattableTextComponent func_240699_a_(TextFormatting formatting);
}
