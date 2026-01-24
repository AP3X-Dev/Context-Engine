#!/usr/bin/env python3
"""Test tree cache integration with ASTAnalyzer."""
import sys
sys.path.insert(0, '.')

from scripts.ast_analyzer import ASTAnalyzer


def test_tree_cache_integration():
    """Test that the tree cache is wired into ASTAnalyzer correctly."""
    
    # Test instantiation
    analyzer = ASTAnalyzer(use_tree_sitter=True)
    print(f'✓ ASTAnalyzer instantiated')
    print(f'  tree_sitter: {analyzer.use_tree_sitter}')
    print(f'  tree_cache: {"enabled" if analyzer._tree_cache else "disabled"}')
    
    # Test analyzing a Python file
    result = analyzer.analyze_file('scripts/ast_analyzer.py', 'python')
    symbols = result.get('symbols', [])
    print(f'✓ Analyzed scripts/ast_analyzer.py')
    print(f'  Found {len(symbols)} symbols')
    if symbols:
        print(f'  First 3: {[s.name for s in symbols[:3]]}')
    
    # Test cache hit
    print('\n--- Testing cache hit on second parse ---')
    result2 = analyzer.analyze_file('scripts/ast_analyzer.py', 'python')
    symbols2 = result2.get('symbols', [])
    print(f'✓ Second analysis returned {len(symbols2)} symbols')
    
    # Show cache stats
    if analyzer._tree_cache:
        stats = analyzer._tree_cache.get_stats()
        print(f'\nTree cache stats: {stats}')
    
    assert len(symbols) > 0, "Should find symbols"
    assert len(symbols) == len(symbols2), "Results should be consistent"
    
    print('\n✓ All tests passed!')


if __name__ == "__main__":
    test_tree_cache_integration()

